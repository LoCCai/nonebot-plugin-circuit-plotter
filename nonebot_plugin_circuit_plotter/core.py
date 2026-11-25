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
_TWO_PIN = {"R", "C", "L", "D", "LED", "SW", "V"}
_GATES = {"AND", "OR", "NOT", "OPAMP"}
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
    "R/C/L/D/LED/SW/V 编号 节点A 节点B [数值]（两节点同横或同纵，间隔至少两格）；"
    "AND/OR/OPAMP 编号 输入1 输入2 输出，NOT 编号 输入 输出；"
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


def _identifier(value):
    if not _IDENT.fullmatch(value):
        raise CircuitError("名称须从英文字母开始，最多 24 个字母、数字或下划线")
    return value


def _text(value):
    if not 1 <= len(value) <= 64 or not value.isprintable():
        raise CircuitError("标注须为 1 至 64 个可显示字符")
    return value


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
            elif kind == "label":
                fields = rest.split(maxsplit=1)
                if len(fields) != 2:
                    raise CircuitError("格式为 label 节点 文字")
                parts.append(Part(kind, "", (fields[0],), _text(fields[1]), number))
            elif kind.upper() in _TWO_PIN | _GATES:
                kind = kind.upper()
                pin_count = 3 if kind in _GATES - {"NOT"} else 2
                fields = rest.split(maxsplit=pin_count + 1)
                if not pin_count + 1 <= len(fields) <= pin_count + 2:
                    raise CircuitError(f"{kind} 需要元件编号和 {pin_count} 个引脚节点")
                name = _identifier(fields[0])
                if name in names:
                    raise CircuitError("元件编号已使用")
                names.add(name)
                value = _text(fields[-1]) if len(fields) == pin_count + 2 else ""
                parts.append(Part(kind, name, tuple(fields[1:pin_count+1]), value, number))
            else:
                raise CircuitError("未知指令或元件类型")
        except CircuitError as error:
            raise CircuitError(f"第 {number} 行 · {error}") from None
    if len(nodes) > 56 or len(parts) > 64:
        raise CircuitError("最多 56 个节点和 64 条连线、标注或元件")
    if not nodes or not any(part.kind not in {"ground", "label"} for part in parts):
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
    edges = {"C": (-6, 6), "D": (-13, 13), "LED": (-13, 13), "V": (-16, 16)}
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
    else:
        x, y = centre
        draw.ellipse((x-16, y-16, x+16, y+16), outline=ink, width=3)
        stroke([(-11, 0), (-3, 0)])
        stroke([(-7, -4), (-7, 4)])
        stroke([(3, 0), (10, 0)])
    x, y = centre
    label = f"{part.name}  {part.value}".strip()
    draw.text((x+23, y) if dy else (x, y-27 if kind == "LED" else y-18),
              label, fill=ink, font=_font(14), anchor="lm" if dy else "mb")


def _draw_gate(draw, part, points, ink, wire, bg):
    x0, _ = points[0]
    x1, y = points[-1]
    mid = (x0+x1)/2
    left, right = mid-26, mid+26
    kind = part.kind
    for index, (x, sy) in enumerate(points[:-1]):
        py = y if kind == "NOT" else y+(-10 if index == 0 else 10)
        draw.line([(x, sy), (left-16, sy), (left-16, py), (left, py)], fill=wire, width=3)
    if kind in {"NOT", "OPAMP"}:
        tip = right-7 if kind == "NOT" else right
        draw.polygon([(left, y-23), (tip, y), (left, y+23)], outline=ink, fill=bg, width=3)
        if kind == "NOT":
            draw.ellipse((tip, y-4, tip+8, y+4), outline=ink, width=2)
        else:
            for symbol, py in [("+", y-9), ("−", y+10)]:
                draw.text((left+9, py), symbol, font=_font(14), fill=ink, anchor="mm")
    elif kind == "AND":
        draw.arc((mid-5, y-23, right, y+23), -90, 90, fill=ink, width=3)
        draw.line([(mid+10, y-23), (left, y-23), (left, y+23), (mid+10, y+23)], fill=ink, width=3)
    else:
        draw.line([(left, y-23), (mid+1, y-22), (right, y), (mid+1, y+22), (left, y+23)],
                  fill=ink, width=3, joint="curve")
        draw.arc((left-14, y-23, left+10, y+23), -75, 75, fill=ink, width=3)
    draw.line([(right, y), (x1, y)], fill=wire, width=3)
    draw.text((mid, y-29), f"{part.name}  {part.value or kind}", font=_font(14), fill=ink, anchor="mb")


def render_png(source: str, *, theme: str = "light") -> bytes:
    if theme not in {"light", "dark"}:
        raise CircuitError("主题须为 light 或 dark")
    nodes, parts, title = _parse(source)
    ink, wire, accent, bg = (
        ("#e6eef7", "#80bac5", "#f2bd79", "#151b24") if theme == "dark"
        else ("#1b2636", "#226478", "#9c4a15", "#ffffff")
    )
    min_x = min(x for x, _ in nodes.values())
    min_y = min(y for _, y in nodes.values())
    max_x = max(x for x, _ in nodes.values()) - min_x
    max_y = max(y for _, y in nodes.values()) - min_y
    top = _MARGIN + (36 if title else 0)
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
            elif part.kind == "label":
                x, y = pins[0]
                label_width = draw.textlength(part.value, font=_font(14))
                draw.text((min(x, max(10, width-label_width-10)), y-8),
                          part.value, fill=accent, font=_font(14), anchor="lb")
                continue
            elif part.kind in _GATES:
                _draw_gate(draw, part, pins, ink, wire, bg)
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
