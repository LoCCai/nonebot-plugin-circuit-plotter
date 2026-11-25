"""Optional MoEllmChats tool integration."""
from .core import MAX_SOURCE, TOOL_DESCRIPTION, CircuitError
from .service import render

_TOOL = "render_circuit"


async def _handle(*, _tool_context, source):
    from nonebot_plugin_moellmchats.render_tools import deliver_image
    from nonebot_plugin_moellmchats.tool_contracts import ToolResult

    try:
        png = await render(source)
    except CircuitError as error:
        return ToolResult(text=str(error), structured={"status": "invalid_or_busy"})
    await deliver_image(_tool_context, png)
    return ToolResult(text="原理图已生成并送到当前会话。请说明电路工作原理。",
                      structured={"status": "rendered", "source": source},
                      metadata={"skip_image_vision": True})


def register_tools():
    from nonebot_plugin_moellmchats.tool_contracts import (
        ToolEffect,
        ToolSpec,
        register_tool,
        tool_registry,
    )

    from . import __plugin_meta__

    existing = tool_registry.snapshot().get(_TOOL)
    if existing is None:
        register_tool(ToolSpec(
            name=_TOOL, description=TOOL_DESCRIPTION,
            parameters={"type": "object", "properties": {"source": {"type": "string", "minLength": 1,
                         "maxLength": MAX_SOURCE}}, "required": ["source"], "additionalProperties": False},
            handler=_handle, effect=ToolEffect.READ_ONLY, permission="user", timeout_seconds=20, result_limit=6000,
        ))
    elif existing.handler is not _handle:
        raise ValueError("工具 render_circuit 已由其他插件注册")
    __plugin_meta__.extra["tool_dependencies"] = [_TOOL]
