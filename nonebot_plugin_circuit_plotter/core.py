"""Parse a limited circuit netlist and draw reproducible schematic PNGs."""
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from itertools import pairwise
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

MAX_SOURCE = 5000
_GRID = 64
_MARGIN = 56
_IDENT = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,23}")
_PIN_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_+./-]{0,13}")
_DISPLAY_VALUE = re.compile(r"[0-9](?:\.?[0-9]){0,3}\.?")
_TWO_PIN = {"R", "C", "L", "D", "LED", "SW", "V", "VAC", "BAT"}
_GATES = {"AND", "OR", "NOT", "OPAMP"}
_BLOCKS = {"IC", "MODULE", "DISPLAY"}
_ALIASES = {"与": "AND", "与门": "AND", "或": "OR", "或门": "OR", "非": "NOT", "非门": "NOT",
            "MCU": "IC", "LED7": "DISPLAY", "VDC": "V"}
_EXAMPLE = """title RC 低通
node IN 1 1
node OUT 5 1
node GND 5 4
R R1 IN OUT 1k
C C1 OUT GND 100n
label IN Vin
label OUT Vout
ground GND"""
EXAMPLE = _EXAMPLE
TOOL_DESCRIPTION = (
    "绘制电路原理图，确定性渲染而且可复制源码。仅提供 source 文本。"
    "先定义 node 名称 x y（整数，x 0~20、y 0~14）；"
    "R/C/L/D/LED/SW/V/VAC/BAT 编号 节点A 节点B [数值]（同横或同纵，相距至少两格，V=直流、VAC=交流、BAT=电池）；"
    "AND/OR/OPAMP 编号 上输入 下输入 输出（输入在同一列，输出在右侧两格以上、高度在两输入之间），"
    "NOT 编号 输入 输出（同一行，输出在右侧两格以上）；"
    "IC/MCU 编号 芯片型号 引脚=节点 …（如 IC U1 ESP32 VCC=PWR IO23=OUT GND=RET）；"
    "MODULE 编号 模块型号 引脚=节点 …（如 MODULE PS1 DC-DC VIN=IN VOUT=OUT GND=RET）；"
    "DISPLAY/LED7 编号 数字 引脚=节点 …（如 DISPLAY DS1 12.3 A=SEG COM=RET）；"
    "芯片、模块和数码管的节点须分在左右两列，两列相距至少四格，每边至少一针。数码管可画 1 至 4 位。"
    "引脚按用户给出或已知的定义写明；电路图只表达接线和显示示例。VCC 节点 [标注] 画电源端。"
    "wire 节点A 节点B [折点…]、ground 节点、label 节点 文字、title 文字。"
    "导线各段同横或同纵。示例：\n" + EXAMPLE
)


class CircuitError(ValueError):
    """The source could not be rendered."""


@dataclass(frozen=True)
class Part:
    kind: str
    name: str
    nodes: tuple[str, ...]
    value: str
    line: int
    pins: tuple[str, ...] = ()


def _identifier(value):
    if not _IDENT.fullmatch(value):
        raise CircuitError("名称须从英文字母开始，最多 24 个字母、数字或下划线")
    return value


def _text(value):
    if not 1 <= len(value) <= 64 or not value.isprintable():
        raise CircuitError("标注须为 1 至 64 个可显示字符")
    return value


def _parse_block(kind, name, fields, line):
    if not 4 <= len(fields) <= 26:
        raise CircuitError(f"格式为 {kind} 编号 型号或显示值 引脚=节点 …，共 2 至 24 针")
    value = _text(fields[1])
    if kind == "DISPLAY" and not _DISPLAY_VALUE.fullmatch(value):
        raise CircuitError("数码管显示值须为 1 至 4 个数字，可带小数点")
    pins, nodes = [], []
    for terminal in fields[2:]:
        label, _, node = terminal.partition("=")
        if not _PIN_LABEL.fullmatch(label):
            raise CircuitError("引脚格式为 引脚=节点，引脚名最多 14 个字符")
        pins.append(label)
        nodes.append(_identifier(node))
    if len({label.upper() for label in pins}) != len(pins) or len(set(nodes)) != len(nodes):
        raise CircuitError("引脚名和引脚节点在同一元件内须各不相同")
    return Part(kind, name, tuple(nodes), value, line, tuple(pins))


def _parse(source):
    if not isinstance(source, str) or not source.strip() or len(source) > MAX_SOURCE:
        raise CircuitError(f"请输入 1 至 {MAX_SOURCE} 字的电路代码")
    nodes, names, parts, occupied = {}, set(), [], set()
    title = ""
    rows = source.splitlines()
    if len(rows) > 120:
        raise CircuitError("电路代码最多 120 行")
    for number, row in enumerate(rows, 1):
        fields = row.split(maxsplit=1)
        if not fields or row.lstrip().startswith("#"):
            continue
        kind, rest = fields[0], fields[1] if len(fields) == 2 else ""
        kind = kind.lower()
        fields = rest.split()
        try:
            if kind == "title":
                if title:
                    raise CircuitError("仅可设置一次标题")
                title = _text(rest)
            elif kind == "node":
                if len(fields) != 3:
                    raise CircuitError("格式为 node 名称 x y")
                name = _identifier(fields[0])
                if not all(re.fullmatch(r"[0-9]{1,2}", token) for token in fields[1:]):
                    raise CircuitError("坐标须为非负整数")
                x, y = map(int, fields[1:])
                if x > 20 or y > 14:
                    raise CircuitError("坐标范围为 x 0~20、y 0~14")
                if name in nodes or (x, y) in occupied:
                    raise CircuitError("节点名或坐标已使用")
                nodes[name] = (x, y)
                occupied.add((x, y))
            elif kind == "wire":
                if not 2 <= len(fields) <= 16:
                    raise CircuitError("格式为 wire 节点A 节点B [折点…]")
                parts.append(Part(kind, "", tuple(fields), "", number))
            elif kind == "ground":
                if len(fields) != 1:
                    raise CircuitError("格式为 ground 节点")
                parts.append(Part(kind, "", tuple(fields), "", number))
            elif kind == "vcc":
                fields = rest.split(maxsplit=1)
                if not fields:
                    raise CircuitError("格式为 VCC 节点 [标注]")
                parts.append(Part(kind, "", (fields[0],), _text(fields[1]) if len(fields) == 2 else "VCC", number))
            elif kind == "label":
                fields = rest.split(maxsplit=1)
                if len(fields) != 2:
                    raise CircuitError("格式为 label 节点 文字")
                parts.append(Part(kind, "", (fields[0],), _text(fields[1]), number))
            elif (symbol := _ALIASES.get(kind.upper(), kind.upper())) in _TWO_PIN | _GATES | _BLOCKS:
                if not fields:
                    raise CircuitError(f"{symbol} 需要元件编号和引脚")
                name = _identifier(fields[0])
                if name in names:
                    raise CircuitError("元件编号已使用")
                names.add(name)
                if symbol in _BLOCKS:
                    parts.append(_parse_block(symbol, name, fields, number))
                else:
                    pin_count = 3 if symbol in _GATES - {"NOT"} else 2
                    fields = rest.split(maxsplit=pin_count + 1)
                    if len(fields) < pin_count + 1:
                        raise CircuitError(f"{symbol} 需要元件编号和 {pin_count} 个引脚节点")
                    value = _text(fields[-1]) if len(fields) == pin_count + 2 else ""
                    parts.append(Part(symbol, name, tuple(fields[1:pin_count+1]), value, number))
            else:
                raise CircuitError("未知指令或元件类型")
        except CircuitError as error:
            raise CircuitError(f"第 {number} 行 · {error}") from None
    if len(nodes) > 56 or len(parts) > 64:
        raise CircuitError("最多 56 个节点和 64 条连线、标注或元件")
    if not nodes or not any(part.kind not in {"ground", "label", "vcc"} for part in parts):
        raise CircuitError("请至少定义一条导线或一个元件")
    for part in parts:
        try:
            points = [nodes[key] for key in part.nodes]
        except KeyError as error:
            raise CircuitError(f"第 {part.line} 行 · 节点 {error.args[0][:24]} 未定义") from None
        if part.kind == "wire" or part.kind in _TWO_PIN:
            for a, b in pairwise(points):
                if (a[0] == b[0]) == (a[1] == b[1]):
                    raise CircuitError(f"第 {part.line} 行 · 须连接同横或同纵的两个不同节点")
                if part.kind in _TWO_PIN and abs(a[0]-b[0]) + abs(a[1]-b[1]) < 2:
                    raise CircuitError(f"第 {part.line} 行 · 元件引脚之间至少留两格")
        elif part.kind in _GATES:
            end = points[-1]
            start = points[0]
            aligned = start[1] == end[1] if part.kind == "NOT" else (
                start[0] == points[1][0] and start[1] < end[1] < points[1][1])
            if end[0]-start[0] < 2 or not aligned:
                raise CircuitError(f"第 {part.line} 行 · 门或运放输入位于左侧，输出与输入中间对齐")
        elif part.kind in _BLOCKS:
            columns = sorted({x for x, _ in points})
            if len(columns) != 2 or columns[1]-columns[0] < 4:
                raise CircuitError(f"第 {part.line} 行 · 引脚须分在左右两列，间隔至少四格")
    return nodes, parts, title


@lru_cache(maxsize=3)
def _font(size):
    for path, index in (
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
        ("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf", 0),
        ("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", 0),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
    ):
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size, index=index)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def _draw_part(draw, part, points, ink, wire, accent, bg):
    a, b = points
    dx, dy = b[0]-a[0], b[1]-a[1]
    half = math.hypot(dx, dy) / 2
    ux, uy = dx/(2*half), dy/(2*half)
    centre = ((a[0]+b[0])/2, (a[1]+b[1])/2)

    def pt(x, y):
        return centre[0]+ux*x-uy*y, centre[1]+uy*x+ux*y

    def stroke(coords, fill=ink):
        draw.line([pt(*point) for point in coords], fill=fill, width=3, joint="curve")

    kind = part.kind
    edges = {"C": (-6, 6), "D": (-13, 13), "LED": (-13, 13), "V": (-18, 18), "VAC": (-18, 18), "BAT": (-12, 12)}
    left, right = edges.get(kind, (-26, 26))
    stroke([(-half, 0), (left, 0)], wire)
    stroke([(right, 0), (half, 0)], wire)
    if kind == "R":
        stroke([(-26, 0), (-20, 0), (-15, -9), (-9, 9), (-3, -9),
                (3, 9), (9, -9), (15, 9), (21, 0), (26, 0)])
    elif kind == "C":
        stroke([(-6, -14), (-6, 14)])
        stroke([(6, -14), (6, 14)])
    elif kind == "L":
        stroke([(-26+i*2, -9*abs(math.sin(math.pi*i/6))) for i in range(27)])
    elif kind in {"D", "LED"}:
        stroke([(-13, -11), (13, 0), (-13, 11), (-13, -11)])
        stroke([(13, -13), (13, 13)])
        if kind == "LED":
            for y in (-11, -18):
                stroke([(1, y), (13, y-10), (7, y-9)], accent)
                stroke([(13, y-10), (12, y-4)], accent)
    elif kind == "SW":
        for x in (-26, 26):
            u, v = pt(x, 0)
            draw.ellipse((u-3, v-3, u+3, v+3), outline=ink, fill=bg, width=2)
        stroke([(-22, -2), (18, -17)])
    elif kind == "BAT":
        stroke([(-12, -16), (-12, 16)])
        stroke([(-4, -9), (-4, 9)])
        stroke([(4, -16), (4, 16)])
        stroke([(12, -9), (12, 9)])
    else:
        x, y = centre
        draw.ellipse((x-18, y-18, x+18, y+18), outline=ink, width=3)
        if kind == "VAC":
            stroke([(i, -6*math.sin(i*math.pi/11)) for i in range(-11, 12)])
        else:
            stroke([(-11, 0), (-3, 0)])
            stroke([(-7, -4), (-7, 4)])
            stroke([(3, 0), (10, 0)])
    x, y = centre
    label = f"{part.name}  {part.value}".strip()
    rise = {"LED": 30, "V": 22, "VAC": 22}.get(kind, 18)
    draw.text((x+23, y) if dy else (x, y-rise),
              label, fill=ink, font=_font(14), anchor="lm" if dy else "mb")


def _cubic(start, control1, control2, end):
    path = []
    for step in range(17):
        t = step/16
        s = 1-t
        path.append(tuple(round(s**3*a + 3*s*s*t*b + 3*s*t*t*c + t**3*d)
                          for a, b, c, d in zip(start, control1, control2, end)))
    return path


def _draw_gate(draw, part, points, ink, wire, bg):
    x0, _ = points[0]
    x1, y = points[-1]
    mid = (x0+x1)//2
    left, right = mid-42, mid+42
    top, bottom = y-28, y+28
    kind = part.kind
    terminals = [(left, y)] if kind == "NOT" else [(left, y-13), (left, y+13)]
    if kind == "OR":
        back = _cubic((left, top), (left+21, y-13), (left+21, y+13), (left, bottom))
        terminals = [back[4], back[12]]

    for (x, sy), (px, py) in zip(points[:-1], terminals):
        draw.line([(x, sy), (left-12, sy), (left-12, py), (px, py)], fill=wire, width=4, joint="curve")
    draw.line([(right, y), (x1, y)], fill=wire, width=4)
    if kind in {"NOT", "OPAMP"}:
        tip = right-12 if kind == "NOT" else right
        draw.polygon([(left, top), (tip, y), (left, bottom)], outline=ink, fill=bg, width=4)
        if kind == "NOT":
            draw.ellipse((tip, y-6, right, y+6), outline=ink, fill=bg, width=3)
        else:
            for symbol, py in [("+", y-13), ("−", y+13)]:
                draw.text((left+13, py), symbol, font=_font(14), fill=ink, anchor="mm")
    elif kind == "AND":
        stem = right-28
        draw.arc((stem-28, top, right, bottom), -90, 90, fill=ink, width=4)
        draw.line([(stem, top), (left, top), (left, bottom), (stem, bottom)], fill=ink, width=4)
    else:
        upper = _cubic((left, top), (mid-2, top-1), (right-18, top+6), (right, y))
        lower = [(x, 2*y-py) for x, py in reversed(upper)]
        draw.line(upper+lower, fill=ink, width=4, joint="curve")
        draw.line(back, fill=ink, width=4, joint="curve")
    draw.text((mid, top-7), f"{part.name}  {part.value or kind}", font=_font(14), fill=ink, anchor="mb")


_SEGMENTS = (((4, -22), (20, -22)), ((23, -18), (23, -4)), ((23, 4), (23, 18)),
             ((4, 22), (20, 22)), ((1, 4), (1, 18)), ((1, -18), (1, -4)), ((4, 0), (20, 0)))
_DIGITS = dict(zip("0123456789", ("abcdef", "bc", "abdeg", "abcdg", "bcfg",
                                  "acdfg", "acdefg", "abc", "abcdefg", "abcdfg")))


def _draw_digits(draw, value, x, y, accent, inactive):
    for digit, dot in re.findall(r"(\d)(\.?)", value):
        for key, segment in zip("abcdefg", _SEGMENTS):
            draw.line([(x+px, y+py) for px, py in segment], fill=accent if key in _DIGITS[digit] else inactive, width=4)
        if dot:
            draw.ellipse((x+27, y+20, x+31, y+24), fill=accent)
        x += 34


def _draw_block(draw, part, points, ink, wire, accent, bg, inactive):
    x0 = min(x for x, _ in points)
    left, right = x0+28, max(x for x, _ in points)-28
    top, bottom = min(y for _, y in points)-36, max(y for _, y in points)+36
    name_font = _font(14)
    pin_font = _font(12)
    pin_left = max(pin_font.getlength(label) for label, (x, _) in zip(part.pins, points) if x == x0)
    pin_right = max(pin_font.getlength(label) for label, (x, _) in zip(part.pins, points) if x != x0)
    left_edge, right_edge = left+10+pin_left, right-10-pin_right
    inner_width = 34*len(part.value.replace(".", "")) if part.kind == "DISPLAY" else 0
    if right_edge-left_edge < inner_width+8:
        raise CircuitError(f"第 {part.line} 行 · 请加宽引脚列间距，为型号或数字留出空间")

    draw.rounded_rectangle((left, top, right, bottom), radius=6, fill=bg, outline=ink, width=3)
    label = part.name if part.kind == "DISPLAY" else f"{part.name}  {part.value}"
    draw.text(((left+right)/2, top-5), label, font=name_font, fill=ink, anchor="mb")
    for label, (x, y) in zip(part.pins, points):
        is_left = x == x0
        edge = left if is_left else right
        draw.line([(x, y), (edge, y)], fill=wire, width=3)
        draw.text((edge+8 if is_left else edge-8, y), label, font=pin_font, fill=ink, anchor="lm" if is_left else "rm")
    if part.kind == "DISPLAY":
        _draw_digits(draw, part.value, (left_edge+right_edge-inner_width)/2, (top+bottom)/2, accent, inactive)


def render_png(source: str, *, theme: str = "light") -> bytes:
    if theme not in {"light", "dark"}:
        raise CircuitError("主题须为 light 或 dark")
    nodes, parts, title = _parse(source)
    ink, wire, accent, bg, inactive = (
        ("#e6eef7", "#80bac5", "#f2bd79", "#151b24", "#533f3b") if theme == "dark"
        else ("#1b2636", "#226478", "#9c4a15", "#ffffff", "#ebd6c9")
    )
    min_x = min(x for x, _ in nodes.values())
    min_y = min(y for _, y in nodes.values())
    max_x = max(x for x, _ in nodes.values()) - min_x
    max_y = max(y for _, y in nodes.values()) - min_y
    top = _MARGIN
    if title:
        top += 56 if any(part.kind in _BLOCKS for part in parts) else 36
    points = {key: ((x-min_x)*_GRID+_MARGIN, (y-min_y)*_GRID+top) for key, (x, y) in nodes.items()}
    text_bounds = [(_MARGIN, _font(20).getlength(title), "start")]
    for part in parts:
        if part.kind in {"wire", "ground"}:
            continue
        x1, _ = points[part.nodes[0]]
        x2, _ = points[part.nodes[-1]]
        if part.kind == "label":
            text_bounds.append((x1, _font(14).getlength(part.value), "start"))
            continue
        if part.kind in _BLOCKS:
            xs = [points[key][0] for key in part.nodes]
            text = part.name if part.kind == "DISPLAY" else f"{part.name}  {part.value}"
            text_bounds.append(((min(xs)+max(xs))/2, _font(14).getlength(text), "centre"))
            continue
        if part.kind == "vcc":
            text_bounds.append((x1, _font(14).getlength(part.value), "centre"))
            continue
        text = f"{part.name}  {part.value or (part.kind if part.kind in _GATES else '')}".strip()
        text_bounds.append((x1+23 if x1 == x2 else (x1+x2)/2, _font(14).getlength(text),
                            "start" if x1 == x2 else "centre"))
    left_pad = max(0, math.ceil(max((width/2 - x + 12 for x, width, align in text_bounds
                                   if align == "centre"), default=0)))
    if left_pad:
        points = {key: (x+left_pad, y) for key, (x, y) in points.items()}
    text_right = max(x + (width if align == "start" else width/2) for x, width, align in text_bounds)
    width = max(360, max_x*_GRID+2*_MARGIN, math.ceil(text_right)+18) + left_pad
    height = max(152, max_y*_GRID+top+_MARGIN)
    with Image.new("RGB", (width, height), bg) as image:
        draw = ImageDraw.Draw(image)
        if title:
            draw.text((_MARGIN, 19), title, fill=ink, font=_font(20))
        uses = dict.fromkeys(nodes, 0)
        for part in parts:
            pins = [points[key] for key in part.nodes]
            if part.kind == "wire":
                draw.line(pins, fill=wire, width=3, joint="curve")
                for key in part.nodes[1:-1]:
                    uses[key] += 1
            elif part.kind == "ground":
                x, y = pins[0]
                draw.line((x, y, x, y+14), fill=wire, width=3)
                for span, down in [(12, 14), (8, 19), (4, 24)]:
                    draw.line((x-span, y+down, x+span, y+down), fill=ink, width=2)
            elif part.kind == "vcc":
                x, y = pins[0]
                draw.line((x, y, x, y-18), fill=wire, width=3)
                draw.line((x-10, y-18, x+10, y-18), fill=ink, width=3)
                draw.text((x, y-23), part.value, fill=accent, font=_font(14), anchor="mb")
            elif part.kind == "label":
                x, y = pins[0]
                label_width = draw.textlength(part.value, font=_font(14))
                draw.text((min(x, max(10, width-label_width-10)), y-8),
                          part.value, fill=accent, font=_font(14), anchor="lb")
                continue
            elif part.kind in _GATES:
                _draw_gate(draw, part, pins, ink, wire, bg)
            elif part.kind in _BLOCKS:
                _draw_block(draw, part, pins, ink, wire, accent, bg, inactive)
            else:
                _draw_part(draw, part, pins, ink, wire, accent, bg)
            for key in part.nodes:
                uses[key] += 1
        for key, count in uses.items():
            if count >= 3:
                x, y = points[key]
                draw.ellipse((x-4, y-4, x+4, y+4), fill=wire)
        with BytesIO() as out:
            image.save(out, format="PNG")
            return out.getvalue()
