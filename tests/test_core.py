import io

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
