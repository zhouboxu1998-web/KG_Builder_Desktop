"""统一 Tool Runtime：输入校验、计时、异常包装与日志。"""
from __future__ import annotations

import inspect
from time import perf_counter
from typing import Any, Callable, Dict

from kg_builder.core.errors import ToolExecutionError, ToolInputError
from kg_builder.core.logger import get_logger

logger = get_logger(__name__)


class ToolRuntime:
    def __init__(self, tool: Callable[..., Any], name: str | None = None):
        self.tool = tool
        self.name = name or getattr(tool, "__name__", "tool")

    def _validate(self, kwargs: Dict[str, Any]) -> None:
        try:
            signature = inspect.signature(self.tool)
            signature.bind(**kwargs)
        except TypeError as error:
            raise ToolInputError(
                f"Tool '{self.name}' 输入参数不符合函数签名。",
                details={"tool": self.name, "error": str(error)},
                cause=error,
            ) from error

    def run(self, **kwargs: Any) -> Any:
        self._validate(kwargs)
        started = perf_counter()
        try:
            result = self.tool(**kwargs)
            logger.info(
                "Tool finished",
                extra={"structured": {"tool": self.name, "duration_ms": (perf_counter() - started) * 1000}},
            )
            return result
        except ToolInputError:
            raise
        except Exception as error:
            raise ToolExecutionError(
                f"Tool '{self.name}' 执行失败。",
                details={"tool": self.name},
                cause=error,
            ) from error

    async def run_async(self, **kwargs: Any) -> Any:
        self._validate(kwargs)
        started = perf_counter()
        try:
            result = self.tool(**kwargs)
            if inspect.isawaitable(result):
                result = await result
            logger.info(
                "Tool finished",
                extra={"structured": {"tool": self.name, "duration_ms": (perf_counter() - started) * 1000}},
            )
            return result
        except ToolInputError:
            raise
        except Exception as error:
            raise ToolExecutionError(
                f"Tool '{self.name}' 执行失败。",
                details={"tool": self.name},
                cause=error,
            ) from error


__all__ = ["ToolRuntime"]
