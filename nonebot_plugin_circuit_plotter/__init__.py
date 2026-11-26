from nonebot import get_driver
from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="电路图绘制",
    description="按电路代码绘制电路原理图，也可由七七 AI 从文字需求生成代码。",
    usage="/画电路 后发送电路代码，或把代码跟在命令后。/电路图帮助 查看语法和示例。",
    type="application",
    homepage="https://github.com/LoCCai/nonebot-plugin-circuit-plotter",
    supported_adapters={"~onebot.v11"},
    extra={
        "menu_data": [
            {"func": "画电路", "trigger_method": "指令",
             "trigger_condition": "/画电路 [多行电路代码]", "brief_des": "生成电路原理图 PNG",
             "detail_des": "发送 /画电路，再发送代码，或把多行代码写在同一条消息中。"},
            {"func": "电路图帮助", "trigger_method": "指令",
             "trigger_condition": "/电路图帮助", "brief_des": "查看电路语法和 RC 低通示例",
             "detail_des": "支持基础元件、逻辑门、芯片、电源模块、数码管、导线和节点标注。"},
        ],
    },
)

try:
    get_driver()
except ValueError:
    pass
else:
    from . import plugin as plugin
