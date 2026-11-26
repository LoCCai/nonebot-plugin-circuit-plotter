import io
from collections import deque

import pytest
from PIL import Image

from nonebot_plugin_circuit_plotter.core import EXAMPLE, CircuitError, render_png


def test_real_deterministic_schematic_in_light_and_dark():
    src = EXAMPLE
    light, dark = render_png(src), render_png(src, theme="dark")
    assert render_png(src) == light and dark != light
    for png in (light, dark):
        with Image.open(io.BytesIO(png)) as image:
            assert image.format == "PNG"
            assert image.width >= 300 and image.height >= 250
            assert image.getcolors(16_000) and len(image.getcolors(16_000)) > 10


@pytest.mark.parametrize(("tail", "message"), [
    ("node X 1 1", "坐标已使用"),
    ("wire MISSING IN", "未定义"),
    ("LED D1 IN GND", "同横或同纵"),
    ("script alert(1)", "未知指令"),
])
def test_rejects_invalid_code_with_line_number(tail, message):
    with pytest.raises(CircuitError, match=message) as error:
        render_png(EXAMPLE + "\n" + tail)
    assert f"第 {len(EXAMPLE.splitlines()) + 1} 行" in str(error.value)


def test_three_pin_gate_and_two_pin_diode_have_visible_raster():
    src = """
title 阀值逻辑
node A 1 1
node B 1 3
node Y 4 2
node X 7 2
OPAMP U1 A B Y
LED D1 Y X 2V
"""
    assert render_png(src).startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize("name", ["AND", "或门", "XOR", "NAND", "NOR", "XNOR"])
def test_gate_pins_touch_the_outline(name):
    source = f"node A 1 1\nnode B 1 3\nnode Y 3 2\n{name} U1 A B Y"
    with Image.open(io.BytesIO(render_png(source))) as image:
        pixels = image.load()
        start = (56, 56)
        queue = deque([start])
        visited = {start}
        while queue:
            x, y = queue.popleft()
            for point in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
                if point not in visited and pixels[point] != (255, 255, 255):
                    visited.add(point)
                    queue.append(point)
        assert {(56, 184), (184, 120)} <= visited


def test_inverter_has_a_hollow_bubble_joining_the_output():
    source = "node A 1 1\nnode Y 3 1\n非门 U1 A Y"
    with Image.open(io.BytesIO(render_png(source))) as image:
        assert image.getpixel((156, 56)) == (255, 255, 255)
        assert image.getpixel((160, 56)) == (27, 38, 54)
        assert image.getpixel((163, 56)) == (34, 100, 120)


@pytest.mark.parametrize("theme,lit", [("light", (156, 74, 21)), ("dark", (242, 189, 121))])
def test_display_renders_distinct_digits_and_a_decimal_point(theme, lit):
    source = "node A 1 1\nnode B 6 1\nLED7 DS1 {} A=A COM=B"
    with Image.open(io.BytesIO(render_png(source.format("1"), theme=theme))) as one, \
         Image.open(io.BytesIO(render_png(source.format("8"), theme=theme))) as eight, \
         Image.open(io.BytesIO(render_png(source.format("8."), theme=theme))) as decimal:
        def lit_pixels(image):
            return sum(c for c, colour in image.getcolors(16_000) if colour == lit)
        assert 0 < lit_pixels(one) < lit_pixels(eight) < lit_pixels(decimal)


@pytest.mark.parametrize(("part", "message"), [
    ("DISPLAY U1 12345 A=L B=R", "1 至 4 个数字"),
    ("IC U1 ESP32 GPIO0=L gpio0=R", "须各不相同"),
    ("MODULE PS1 DC-DC VIN=L GND=L VOUT=R", "须各不相同"),
    ("MCU U1 ESP32 VCC=L IO0=M GND=R", "左右两列"),
    ("IC U1 ESP32 VCC=L GND=Z", "节点 Z 未定义"),
])
def test_named_pins_validate_geometry_and_references(part, message):
    source = "node L 1 1\nnode M 3 2\nnode R 7 1\n" + part
    with pytest.raises(CircuitError, match=f"第 4 行 · .*{message}"):
        render_png(source)
