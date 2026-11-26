# NoneBot2 电路图绘制

通过简洁的电路代码绘制电路原理图。支持 OneBot v11 群指令、PicMenu Next 菜单和可选的 MoEllmChats 工具。七七的 QWeb 与 Android AI 对话可以解析 `circuit` Markdown 代码块，保存 PNG、复制源码或导出带源码的 Markdown。

## 安装

```sh
pip install git+https://github.com/LoCCai/nonebot-plugin-circuit-plotter.git
```

在 NoneBot 项目中加载 `nonebot_plugin_circuit_plotter`。可用 `/电路图帮助` 查看语法，发 `/画电路` 后再发源码，或把代码放在同一条消息里。命令前缀由宿主配置决定。

已有 MoEllmChats 时，在宿主加载插件后调用 `nonebot_plugin_circuit_plotter.llm.register_tools()`。`render_circuit` 接受一个 `source` 参数，在当前会话发送图。

## RC 低通

```circuit
title RC 低通
node IN 1 1
node OUT 5 1
node GND 5 4
R R1 IN OUT 1k
C C1 OUT GND 100n
label IN Vin
label OUT Vout
ground GND
```

- `node 名称 x y` 定义整数网格坐标。横轴 0 至 20，纵轴 0 至 14。名称从字母开始，后续可用字母、数字或下划线。
- `R|C|L|D|LED|SW|V|VAC|BAT 编号 节点A 节点B [值]` 对应电阻、电容、电感、二极管、发光二极管、开关、直流电压源、交流电压源和电池。二引脚元件在同横线或纵线，间隔至少两格。二极管按阳极、阴极填写，直流和电池按正、负端填写。
- `AND|OR|OPAMP 编号 上输入 下输入 输出 [标注]`。两输入在左侧同一列，输出在右侧至少两格且纵坐标位于两输入之间。运放上端是正输入。取反门用 `NOT 编号 输入 输出`，两端同一行。与、或、非也可以写作 `与门`、`或门`、`非门`。
- `IC 编号 型号 引脚=节点 …` 绘制带命名引脚的芯片，可写作 `MCU`。电源等模块用 `MODULE 编号 型号 引脚=节点 …`。每个元件可标 2 至 24 个引脚，节点分布于左右两列，两列至少相隔四格。型号一个字段，引脚和节点各自唯一。引脚含义由提交的原理图代码指定。
- `DISPLAY 编号 显示值 引脚=节点 …` 绘制 1 至 4 位 LED 七段数码管，可含小数点，也可用 `LED7`。引脚分布规则与芯片相同。显示值是静态展示的样例。
- `wire 节点A 节点B [折点…]` 按节点顺序画正交导线。同名节点相连。交叉需要连接时，在交点显式共享节点。节点连接三条或更多支路时会画连接点。
- `ground 节点` 画接地符号，`VCC 节点 [标注]` 画电源端。可选 `label 节点 文字`、`title 标题`。以 `#` 开头的行是注释。

## 单片机与数码管模块

```circuit
title 单片机与七段显示模块
node PWR 1 2
node RET 1 4
node IO18 7 2
node IO19 7 3
node CLK 9 2
node DATA 9 3
node DISP_PWR 16 2
node DISP_RET 16 4
MCU U1 ESP32 VCC=PWR GND=RET IO18=IO18 IO19=IO19
DISPLAY DS1 12.3 CLK=CLK DIO=DATA VCC=DISP_PWR GND=DISP_RET
wire IO18 CLK
wire IO19 DATA
VCC PWR +3.3V
VCC DISP_PWR +3.3V
ground RET
ground DISP_RET
```

渲染器限制输入体积、行数、节点数和画布尺寸。原理图用于表达连接，电气参数与工作状态需要单独核算。系统安装 Noto Sans CJK 或 Droid Sans Fallback 时，图中可直接使用中文标签。

## 本地调用

```python
from nonebot_plugin_circuit_plotter.core import EXAMPLE, render_png

png = render_png(EXAMPLE, theme="dark")
```

`python -m pytest` 运行渲染回归。
