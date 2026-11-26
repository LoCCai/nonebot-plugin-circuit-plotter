"""Compile explicit ascending LED counter requests into a checked circuit layout."""

import re
import unicodedata
from dataclasses import dataclass

_DIGITS = '零一二三四五六七八九'
_NUMBER = r'(?:[0-9]{1,4}|[零一二两三四五六七八九十]{1,3})'
_REQUEST = re.compile(
    r'\s*(?:(?:请|麻烦|帮我|帮忙|给我|七七)\s*)*'
    r'(?:画|绘制|生成)(?:一(?:个|张|幅))?\s*(?:带)?\s*'
    r'(?:LED(?:七段)?(?:数码管)?|七段数码管|数码管)\s*(?:显示)?(?:的)?计数器'
    r'(?:的?(?:电路图|原理图|接线图))?\s*[,，:：]?\s*'
    rf'从\s*(?P<first>{_NUMBER})\s*(?:开始\s*[,，]?\s*)?'
    r'(?:(?:每跳|每次按键|每次|每个脉冲)\s*(?:加\s*[1一]|递增)\s*[,，]?\s*)?'
    rf'(?:到|至|计到|数到)\s*(?P<last>{_NUMBER})\s*(?:时|后|再)?\s*'
    r'(?P<reset>复位|循环|回到(?:起点|初值|初始值)|归零)\s*[。.!！]?\s*', re.IGNORECASE,
)

_LAYOUT = '''node BTN 1 4
node BTN_GND 1 7
node U_PWR 5 2
node PULSE 5 4
node U_GND 5 6
node D3 11 3
node D4 11 4
node CLK 13 3
node DIO 13 4
node DS_PWR 19 2
node DS_GND 19 6
IC U1 Arduino-Nano 5V=U_PWR D2=PULSE GND=U_GND D3=D3 D4=D4
DISPLAY TM1637 {last} CLK=CLK DIO=DIO VCC=DS_PWR GND=DS_GND
wire BTN PULSE
wire D3 CLK
wire D4 DIO
SW SW1 BTN BTN_GND 计数
label BTN D2 内置上拉
VCC U_PWR +5V
VCC DS_PWR +5V
ground BTN_GND
ground U_GND
ground DS_GND'''


def _value(token: str) -> int:
    if token.isascii():
        return int(token)
    token = token.replace('两', '二')
    if '十' in token:
        tens, ones = token.split('十')
        return 10 * (_DIGITS.index(tens) if tens else 1) + (_DIGITS.index(ones) if ones else 0)
    return _DIGITS.index(token)


@dataclass(frozen=True)
class Counter:
    first: int
    last: int

    @property
    def source(self) -> str:
        return f'title {self.first}–{self.last} LED 计数器\n' + _LAYOUT.format(last=self.last)

    @property
    def explanation(self) -> str:
        return (f'Arduino Nano 的 D2 使用内置上拉，按键接地触发一次计数。D3 接 TM1637 的 CLK，'
                f'D4 接 DIO，两边共用 5V 和地。上电显示 {self.first}，每次有效触发加 1，'
                f'显示 {self.last} 后下一次触发回到 {self.first}。')


def parse_counter_request(text: str) -> Counter | None:
    if not isinstance(text, str) or len(text) > 160 or '\n' in text.strip():
        return None
    match = _REQUEST.fullmatch(unicodedata.normalize('NFKC', text))
    if not match:
        return None
    try:
        first, last = _value(match['first']), _value(match['last'])
    except ValueError:
        return None
    if first >= last or (match['reset'] == '归零' and first != 0):
        return None
    return Counter(first, last)
