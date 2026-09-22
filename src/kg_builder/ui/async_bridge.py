"""
asyncio 与 Tkinter 的桥接。

设计：

    Tkinter 主线程
          │
          │ submit(coroutine)
          ▼
    AsyncBridge
          │
          ▼
    后台 asyncio Event Loop
          │
          ▼
       Agent / IO

目标：

    1. GUI 主线程永不执行长时间 asyncio 任务。
    2. Agent 请求不会阻塞 Tkinter。
    3. Bridge 可以安全启动与关闭。
    4. 重复 stop 不会产生额外异常。
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from typing import Coroutine, Optional


class AsyncBridge:
    """
    在后台线程运行 asyncio Event Loop。

    主线程：

        future = bridge.submit(coro)

    关闭：

        bridge.stop()
    """

    def __init__(
        self,
        thread_name: str = "asyncio-bridge",
    ):
        self._loop = asyncio.new_event_loop()

        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name=thread_name,
        )

        self._started = threading.Event()
        self._stopped = threading.Event()

        self._closing = False

        self._thread.start()

        # 等待后台线程真正安装 Event Loop。
        if not self._started.wait(timeout=5):
            raise RuntimeError(
                "AsyncBridge asyncio Event Loop 启动超时"
            )

    # ========================================================
    # Event Loop
    # ========================================================

    def _run_loop(self) -> None:
        """后台线程入口。"""
        asyncio.set_event_loop(
            self._loop
        )

        self._started.set()

        try:
            self._loop.run_forever()
        finally:
            try:
                # 关闭异步生成器。
                self._loop.run_until_complete(
                    self._loop.shutdown_asyncgens()
                )
            except Exception:
                pass

            try:
                self._loop.close()
            except Exception:
                pass

            self._stopped.set()

    # ========================================================
    # Submit
    # ========================================================

    def submit(
        self,
        coro: Coroutine,
    ) -> Future:
        """
        向后台 Event Loop 提交协程。

        Returns:
            concurrent.futures.Future
        """

        if self._closing:
            # 防止 coroutine 因为没有被调度而产生：
            # RuntimeWarning: coroutine was never awaited
            try:
                coro.close()
            except Exception:
                pass

            raise RuntimeError(
                "AsyncBridge 已关闭，无法提交新的协程"
            )

        if self._loop.is_closed():
            try:
                coro.close()
            except Exception:
                pass

            raise RuntimeError(
                "AsyncBridge Event Loop 已关闭"
            )

        return asyncio.run_coroutine_threadsafe(
            coro,
            self._loop,
        )

    # ========================================================
    # Status
    # ========================================================

    @property
    def is_running(self) -> bool:
        """Event Loop 是否正在运行。"""
        return (
            self._started.is_set()
            and not self._stopped.is_set()
            and not self._closing
        )

    @property
    def is_closed(self) -> bool:
        """Bridge 是否已经关闭。"""
        return self._stopped.is_set()

    # ========================================================
    # Stop
    # ========================================================

    def stop(
        self,
        timeout: float = 5.0,
    ) -> None:
        """
        停止后台 Event Loop。

        该方法可以重复调用。
        """

        if self._closing:
            return

        self._closing = True

        if self._loop.is_closed():
            return

        try:
            self._loop.call_soon_threadsafe(
                self._loop.stop
            )
        except RuntimeError:
            # Event Loop 已经进入关闭阶段。
            pass

        # 等待后台线程退出。
        if (
            self._thread.is_alive()
            and threading.current_thread()
            is not self._thread
        ):
            self._thread.join(
                timeout=timeout
            )

    # ========================================================
    # Context Manager
    # ========================================================

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        self.stop()