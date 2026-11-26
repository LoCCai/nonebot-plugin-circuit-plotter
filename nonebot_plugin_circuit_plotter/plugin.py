from typing import Annotated

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.params import ArgPlainText, CommandArg
from nonebot.typing import T_State

from .core import TOOL_DESCRIPTION, CircuitError
from .counter import parse_counter_request
from .service import render

draw = on_command("画电路", priority=15, block=True)
help_command = on_command("电路图帮助", priority=14, block=True)


@help_command.handle()
async def circuit_help():
    await help_command.finish("用法：/画电路 后发送代码，或把代码跟在命令后。\n\n" + TOOL_DESCRIPTION)


@draw.handle()
async def receive_arguments(state: T_State, args: Annotated[Message, CommandArg()]):
    if args.extract_plain_text().strip():
        state["circuit_source"] = args


@draw.got("circuit_source", prompt="请发送电路代码。查看示例用 /电路图帮助。")
async def draw_circuit(source: Annotated[str, ArgPlainText("circuit_source")]):
    source = source.strip()
    counter = parse_counter_request(source)
    if counter is not None:
        source = counter.source
    if source.startswith("```circuit\n") and source.endswith("\n```"):
        source = source[len("```circuit\n"):-len("\n```")]
    try:
        png = await render(source)
    except CircuitError as error:
        await draw.finish(str(error))
    output = MessageSegment.image(png)
    await draw.finish(output + MessageSegment.text('\n' + counter.explanation) if counter else output)
