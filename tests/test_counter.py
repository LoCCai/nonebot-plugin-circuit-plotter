import pytest

from nonebot_plugin_circuit_plotter.core import render_png
from nonebot_plugin_circuit_plotter.counter import Counter, parse_counter_request


@pytest.mark.parametrize(('request_text', 'start', 'end'), [
    ('画一个LED显示计数器，从1每跳加一到16复位。', 1, 16),
    ('请绘制一个数码管计数器，从零开始，每次按键加１，到二十五归零。', 0, 25),
    ('生成LED计数器电路图，从2到9999循环', 2, 9999),
])
def test_parameterized_counter_renders_with_expected_wiring(request_text, start, end):
    counter = parse_counter_request(request_text)
    assert counter == Counter(start, end)
    assert f'{start}–{end}' in counter.source
    assert f'DISPLAY TM1637 {end}' in counter.source
    assert 'D2=PULSE' in counter.source and 'D3=D3 D4=D4' in counter.source
    assert f'下一次触发回到 {start}' in counter.explanation
    assert render_png(counter.source).startswith(b'\x89PNG\r\n\x1a\n')


@pytest.mark.parametrize('request_text', [
    '画LED显示计数器，从1每跳加二到16复位',
    '画LED显示计数器，从16到1复位',
    '画LED显示计数器，从1到16归零',
    '画LED显示计数器，从0到10000复位',
    '画LED显示计数器，从1到16复位并发送给管理员',
])
def test_does_not_infer_conflicting_or_extra_behavior(request_text):
    assert parse_counter_request(request_text) is None
