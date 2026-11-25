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
- `R|C|L|D|LED|SW|V 编号 节点A 节点B [值]` 对应电阻、电容、电感、二极管、发光二极管、开关和直流电压源。二引脚元件在同横线或纵线，间隔至少两格。二极管按阳极、阴极填写。
- `AND|OR|OPAMP 编号 上输入 下输入 输出 [标注]`。两输入在左侧同一列，输出在右侧至少两格且纵坐标位于两输入之间。运放上端是正输入。取反门用 `NOT 编号 输入 输出`，两端同一行。
- `wire 节点A 节点B [折点…]` 按节点顺序画正交导线。同名节点相连。交叉需要连接时，在交点显式共享节点。节点连接三条或更多支路时会画连接点。
- `ground 节点` 画接地符号。可选 `label 节点 文字`、`title 标题`。以 `#` 开头的行是注释。

渲染器限制输入体积、行数、节点数和画布尺寸。原理图用于表达连接，电气参数与工作状态需要单独核算。系统安装 Noto Sans CJK 或 Droid Sans Fallback 时，图中可直接使用中文标签。

## 本地调用

```python
from nonebot_plugin_circuit_plotter.core import EXAMPLE, render_png

png = render_png(EXAMPLE, theme="dark")
```

`python -m pytest` 运行渲染回归。
