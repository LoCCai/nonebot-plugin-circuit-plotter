"""Bound rendering work across callers in the same process."""
import asyncio

from .core import CircuitError, render_png

MAX_PNG_BYTES = 1_048_576
_slots = asyncio.Semaphore(2)


class RendererBusy(CircuitError):
    pass


async def render(source: str, *, theme: str = "light") -> bytes:
    if _slots.locked():
        raise RendererBusy("电路图绘制繁忙，请稍后重试")
    await _slots.acquire()
    job = asyncio.create_task(asyncio.to_thread(render_png, source, theme=theme))

    def release(task):
        _slots.release()
        if not task.cancelled():
            task.exception()

    job.add_done_callback(release)
    png = await asyncio.shield(job)
    if len(png) > MAX_PNG_BYTES:
        raise CircuitError("电路图像过大，请拆成多张绘制")
    return png
