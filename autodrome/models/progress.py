from typing import Awaitable, Callable, Optional

ProgressCallback = Callable[[str, Optional[int], Optional[int], Optional[int]], Awaitable[None]]


async def report_progress(callback, phase, current=None, total=None, completed=None):
    if callback is not None:
        await callback(phase, current, total, completed)
