"""asyncio 与 tkinter 的桥接。"""
import asyncio
import threading
from concurrent.futures import Future
from typing import Any, Callable, Coroutine, Optional


class AsyncBridge:
    """在后台线程运行 asyncio 事件循环，主线程通过 submit 提交协程。"""

    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="asyncio-bridge"
        )
        self._thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def submit(self, coro: Coroutine) -> Future:
        """提交协程，返回 concurrent.futures.Future。"""
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self):
        self._loop.call_soon_threadsafe(self._loop.stop)