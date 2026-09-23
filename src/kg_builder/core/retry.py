"""
KG Builder 统一 Retry / Timeout 策略。

设计目标：

1. 提供同步 / 异步统一的 RetryPolicy。
2. 提供同步 / 异步统一的 TimeoutPolicy。
3. Retry 与 Timeout 可以组合使用。
4. Retry 只针对明确允许重试的异常。
5. 保留原始 exception cause，方便 Runtime / Logging 追踪。
6. 默认策略尽量保守，不改变已有业务的副作用语义。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import random
import time
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Awaitable, Callable, Optional, Tuple, Type, TypeVar

from kg_builder.core.logger import get_logger
from kg_builder.core.errors import (
    KGBuilderError,
    OperationTimeoutError,
    RetryExhaustedError,
)


T = TypeVar("T")

logger = get_logger(__name__)

ExceptionTuple = Tuple[Type[BaseException], ...]


DEFAULT_RETRYABLE_EXCEPTIONS: ExceptionTuple = (
    TimeoutError,
    ConnectionError,
    OSError,
)


@dataclass(frozen=True)
class RetryPolicy:
    """描述一次操作的重试策略。"""

    max_attempts: int = 1
    initial_delay: float = 0.5
    max_delay: float = 5.0
    multiplier: float = 2.0
    jitter: float = 0.0
    retryable_exceptions: ExceptionTuple = field(
        default=DEFAULT_RETRYABLE_EXCEPTIONS
    )

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts 必须 >= 1。")

        if self.initial_delay < 0:
            raise ValueError("initial_delay 必须 >= 0。")

        if self.max_delay < 0:
            raise ValueError("max_delay 必须 >= 0。")

        if self.multiplier < 1:
            raise ValueError("multiplier 必须 >= 1。")

        if self.jitter < 0:
            raise ValueError("jitter 必须 >= 0。")

    def delay_for_retry(self, retry_index: int) -> float:
        """
        返回下一次重试前等待时间。

        retry_index 从 0 开始：

            0 -> initial_delay
            1 -> initial_delay * multiplier
            2 -> initial_delay * multiplier^2
        """

        delay = self.initial_delay * (
            self.multiplier ** retry_index
        )

        delay = min(
            delay,
            self.max_delay,
        )

        if self.jitter > 0:
            delay += random.uniform(
                0,
                self.jitter,
            )

        return delay

    def should_retry(self, error: BaseException) -> bool:
        """判断指定异常是否允许重试。"""

        if isinstance(
            error,
            self.retryable_exceptions,
        ):
            return True

        # KGBuilderError 可能只是对底层 transient exception 的包装。
        # 向 cause 链检查，避免包装后丢失 retryability。
        cause = getattr(
            error,
            "cause",
            None,
        )

        if cause is not None and cause is not error:
            return self.should_retry(cause)

        if isinstance(
            error,
            KGBuilderError,
        ):
            return False

        return False


@dataclass(frozen=True)
class TimeoutPolicy:
    """描述一次操作的超时策略。"""

    timeout_seconds: Optional[float] = None

    def __post_init__(self) -> None:
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds 必须 > 0 或为 None。"
            )

    @property
    def enabled(self) -> bool:
        return self.timeout_seconds is not None


async def run_async_with_policy(
    operation: Callable[..., Awaitable[T]],
    *args: Any,
    retry_policy: Optional[RetryPolicy] = None,
    timeout_policy: Optional[TimeoutPolicy] = None,
    operation_name: str = "async_operation",
    **kwargs: Any,
) -> T:
    """
    使用 Retry + Timeout 执行异步操作。

    Timeout 针对每一次 attempt 单独计算。
    也就是说：

        attempts = 3
        timeout = 10s

    最坏情况下总执行时间可能接近：

        3 * 10s + backoff
    """

    retry_policy = retry_policy or RetryPolicy()
    timeout_policy = timeout_policy or TimeoutPolicy()

    last_error: Optional[BaseException] = None

    for attempt in range(
        1,
        retry_policy.max_attempts + 1,
    ):
        try:
            coroutine = operation(
                *args,
                **kwargs,
            )

            if timeout_policy.enabled:
                return await asyncio.wait_for(
                    coroutine,
                    timeout=timeout_policy.timeout_seconds,
                )

            return await coroutine

        except asyncio.CancelledError:
            raise

        except Exception as error:
            last_error = error

            if (
                attempt >= retry_policy.max_attempts
                or not retry_policy.should_retry(error)
            ):
                if (
                    attempt >= retry_policy.max_attempts
                    and retry_policy.max_attempts > 1
                    and retry_policy.should_retry(error)
                ):
                    raise RetryExhaustedError.from_exception(
                        error,
                        message=(
                            f"{operation_name} 达到最大重试次数 "
                            f"({retry_policy.max_attempts})。"
                        ),
                        details={
                            "operation": operation_name,
                            "attempts": attempt,
                        },
                    ) from error

                raise

            delay = retry_policy.delay_for_retry(
                attempt - 1
            )

            logger.warning(
                "Retrying async operation",
                extra={
                    "operation": operation_name,
                    "attempt": attempt,
                    "next_attempt": attempt + 1,
                    "delay_seconds": delay,
                },
            )

            if delay > 0:
                await asyncio.sleep(delay)

    raise RetryExhaustedError.from_exception(
        last_error or RuntimeError(
            f"{operation_name} 执行失败。"
        ),
        message=(
            f"{operation_name} 重试失败。"
        ),
        details={
            "operation": operation_name,
            "attempts": retry_policy.max_attempts,
        },
    )


def run_sync_with_policy(
    operation: Callable[..., T],
    *args: Any,
    retry_policy: Optional[RetryPolicy] = None,
    timeout_policy: Optional[TimeoutPolicy] = None,
    operation_name: str = "sync_operation",
    **kwargs: Any,
) -> T:
    """
    使用 Retry + Timeout 执行同步操作。

    没有 Timeout 时直接调用，不引入线程。

    启用 Timeout 时使用 worker thread 实现 wall-clock 超时。
    Python 无法安全强制终止正在执行的普通线程，因此超时后只会
    停止等待调用方，不保证底层第三方调用线程瞬间终止。
    """

    retry_policy = retry_policy or RetryPolicy()
    timeout_policy = timeout_policy or TimeoutPolicy()

    last_error: Optional[BaseException] = None

    for attempt in range(
        1,
        retry_policy.max_attempts + 1,
    ):
        executor: Optional[
            concurrent.futures.ThreadPoolExecutor
        ] = None

        try:
            if timeout_policy.enabled:
                executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="kg-timeout",
                )

                future = executor.submit(
                    operation,
                    *args,
                    **kwargs,
                )

                try:
                    result = future.result(
                        timeout=timeout_policy.timeout_seconds
                    )
                except concurrent.futures.TimeoutError as error:
                    future.cancel()
                    raise OperationTimeoutError(
                        (
                            f"{operation_name} 超时，"
                            f"超过 {timeout_policy.timeout_seconds} 秒。"
                        ),
                        details={
                            "operation": operation_name,
                            "timeout_seconds": timeout_policy.timeout_seconds,
                            "attempt": attempt,
                        },
                        cause=error,
                    ) from error

                return result

            return operation(
                *args,
                **kwargs,
            )

        except Exception as error:
            last_error = error

            if executor is not None:
                executor.shutdown(
                    wait=False,
                    cancel_futures=True,
                )
                executor = None

            if (
                attempt >= retry_policy.max_attempts
                or not retry_policy.should_retry(error)
            ):
                if (
                    attempt >= retry_policy.max_attempts
                    and retry_policy.max_attempts > 1
                    and retry_policy.should_retry(error)
                ):
                    raise RetryExhaustedError.from_exception(
                        error,
                        message=(
                            f"{operation_name} 达到最大重试次数 "
                            f"({retry_policy.max_attempts})。"
                        ),
                        details={
                            "operation": operation_name,
                            "attempts": attempt,
                        },
                    ) from error

                raise

            delay = retry_policy.delay_for_retry(
                attempt - 1
            )

            logger.warning(
                "Retrying sync operation",
                extra={
                    "operation": operation_name,
                    "attempt": attempt,
                    "next_attempt": attempt + 1,
                    "delay_seconds": delay,
                },
            )

            if delay > 0:
                time.sleep(delay)

        finally:
            if executor is not None:
                executor.shutdown(
                    wait=False,
                    cancel_futures=True,
                )

    raise RetryExhaustedError.from_exception(
        last_error or RuntimeError(
            f"{operation_name} 执行失败。"
        ),
        message=(
            f"{operation_name} 重试失败。"
        ),
        details={
            "operation": operation_name,
            "attempts": retry_policy.max_attempts,
        },
    )


def resilient_async(
    *,
    retry_policy: Optional[RetryPolicy] = None,
    timeout_policy: Optional[TimeoutPolicy] = None,
    operation_name: Optional[str] = None,
):
    """为异步函数提供 Retry + Timeout 装饰器。"""

    def decorator(function):
        name = operation_name or function.__qualname__

        @wraps(function)
        async def wrapper(*args, **kwargs):
            return await run_async_with_policy(
                function,
                *args,
                retry_policy=retry_policy,
                timeout_policy=timeout_policy,
                operation_name=name,
                **kwargs,
            )

        return wrapper

    return decorator


def resilient_sync(
    *,
    retry_policy: Optional[RetryPolicy] = None,
    timeout_policy: Optional[TimeoutPolicy] = None,
    operation_name: Optional[str] = None,
):
    """为同步函数提供 Retry + Timeout 装饰器。"""

    def decorator(function):
        name = operation_name or function.__qualname__

        @wraps(function)
        def wrapper(*args, **kwargs):
            return run_sync_with_policy(
                function,
                *args,
                retry_policy=retry_policy,
                timeout_policy=timeout_policy,
                operation_name=name,
                **kwargs,
            )

        return wrapper

    return decorator


__all__ = [
    "RetryPolicy",
    "TimeoutPolicy",
    "DEFAULT_RETRYABLE_EXCEPTIONS",
    "run_async_with_policy",
    "run_sync_with_policy",
    "resilient_async",
    "resilient_sync",
]
