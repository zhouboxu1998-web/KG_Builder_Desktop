"""
KG Builder 统一日志系统。

Phase 1-B 负责：

    - 统一 Logger 入口
    - Console + Rotating File Handler
    - JSON Lines 结构化日志
    - run_id / stage / agent 等上下文
    - 异常信息结构化记录
    - RuntimeEvent 自动转日志
    - 通用同步 / 异步操作日志装饰器

日志系统与 Runtime Event 的关系：

    RuntimeEvent
        ↓
    AgentRuntime.emit()
        ↓
    Logger
        ├── Console
        └── File

因此 Runtime Event 与 Logging 不相互替代，而是互相连接。
"""

from __future__ import annotations

import contextvars
import hashlib
import inspect
import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional


LOGGER_NAME = "kg_builder"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_DIR = "logs"
DEFAULT_LOG_FILE = "kg_builder.log"
DEFAULT_LOG_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_LOG_BACKUP_COUNT = 5

_SENSITIVE_KEYWORDS = {
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "access_key",
    "private_key",
}

_context: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar(
    "kg_builder_log_context",
    default={},
)

_config_lock = threading.RLock()
_configured = False


# ============================================================
# Context
# ============================================================


def get_log_context() -> Dict[str, Any]:
    """获取当前上下文快照。"""
    return dict(_context.get())


def set_log_context(**values: Any):
    """设置当前异步 / 线程上下文。"""
    current = dict(_context.get())
    current.update(
        {
            key: value
            for key, value in values.items()
            if value is not None
        }
    )
    return _context.set(current)


def reset_log_context(token) -> None:
    """恢复上下文。"""
    _context.reset(token)


@contextmanager
def log_context(**values: Any) -> Iterator[None]:
    """临时设置日志上下文。"""
    token = set_log_context(**values)
    try:
        yield
    finally:
        reset_log_context(token)


# ============================================================
# Safe values
# ============================================================


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(
        keyword in normalized
        for keyword in _SENSITIVE_KEYWORDS
    )


def redact_mapping(
    values: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """复制 mapping 并隐藏常见敏感字段。"""
    if values is None:
        return {}

    result: Dict[str, Any] = {}

    for key, value in values.items():
        key_text = str(key)

        if _is_sensitive_key(key_text):
            result[key_text] = "***REDACTED***"
        else:
            result[key_text] = _safe_value(value)

    return result


def _safe_value(value: Any, depth: int = 0) -> Any:
    """将值转换为适合日志的有限复杂度表示。"""
    if depth > 3:
        return repr(value)[:500]

    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, str) and len(value) > 1000:
            return value[:1000] + "..."
        return value

    if isinstance(value, Mapping):
        return redact_mapping(value)

    if isinstance(value, (list, tuple, set)):
        items = list(value)
        if len(items) > 50:
            items = items[:50]
        return [
            _safe_value(item, depth + 1)
            for item in items
        ]

    return repr(value)[:1000]


def query_fingerprint(query: Optional[str]) -> Optional[str]:
    """生成 Query 的稳定短指纹，不直接记录完整 Cypher。"""
    if query is None:
        return None

    return hashlib.sha256(
        query.strip().encode("utf-8")
    ).hexdigest()[:16]


# ============================================================
# Formatter
# ============================================================


class JsonFormatter(logging.Formatter):
    """JSON Lines 日志格式。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": self.formatTime(
                record,
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        context = get_log_context()
        if context:
            payload.update(
                {
                    key: _safe_value(value)
                    for key, value in context.items()
                }
            )

        for key in (
            "operation",
            "event_type",
            "status",
            "run_id",
            "stage",
            "agent",
            "duration_ms",
            "result_count",
            "error_code",
            "exception_type",
            "query_fingerprint",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = _safe_value(value)

        extra = getattr(record, "structured", None)
        if isinstance(extra, Mapping):
            payload["structured"] = _safe_value(extra)

        if record.exc_info:
            payload["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
            }

        return json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
        )


class ConsoleFormatter(logging.Formatter):
    """人类可读 Console 日志格式。"""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(
            record,
            datefmt="%H:%M:%S",
        )

        fields = []

        for key in (
            "operation",
            "event_type",
            "status",
            "run_id",
            "stage",
            "agent",
            "duration_ms",
            "result_count",
            "error_code",
        ):
            value = getattr(record, key, None)
            if value is not None:
                fields.append(
                    f"{key}={value}"
                )

        context = get_log_context()
        for key in (
            "run_id",
            "stage",
            "agent",
        ):
            if not any(
                f"{key}=" in field
                for field in fields
            ) and key in context:
                fields.append(
                    f"{key}={context[key]}"
                )

        suffix = (
            " | " + " ".join(fields)
            if fields
            else ""
        )

        return (
            f"[{timestamp}] "
            f"{record.levelname:<8} "
            f"{record.name} "
            f"| {record.getMessage()}"
            f"{suffix}"
        )


# ============================================================
# Configuration
# ============================================================


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _load_config() -> Dict[str, Any]:
    """读取日志相关环境变量。"""
    try:
        from kg_builder import config

        log_dir = Path(
            getattr(
                config,
                "LOG_DIR",
                DEFAULT_LOG_DIR,
            )
        )
        log_file = getattr(
            config,
            "LOG_FILE",
            DEFAULT_LOG_FILE,
        )
        level = getattr(
            config,
            "LOG_LEVEL",
            DEFAULT_LOG_LEVEL,
        )
        to_console = getattr(
            config,
            "LOG_TO_CONSOLE",
            True,
        )
        to_file = getattr(
            config,
            "LOG_TO_FILE",
            True,
        )
        json_file = getattr(
            config,
            "LOG_JSON",
            True,
        )
        max_bytes = getattr(
            config,
            "LOG_MAX_BYTES",
            DEFAULT_LOG_MAX_BYTES,
        )
        backup_count = getattr(
            config,
            "LOG_BACKUP_COUNT",
            DEFAULT_LOG_BACKUP_COUNT,
        )
    except Exception:
        log_dir = Path(
            os.getenv(
                "KG_LOG_DIR",
                DEFAULT_LOG_DIR,
            )
        )
        log_file = os.getenv(
            "KG_LOG_FILE",
            DEFAULT_LOG_FILE,
        )
        level = os.getenv(
            "KG_LOG_LEVEL",
            DEFAULT_LOG_LEVEL,
        )
        to_console = _env_bool(
            "KG_LOG_TO_CONSOLE",
            True,
        )
        to_file = _env_bool(
            "KG_LOG_TO_FILE",
            True,
        )
        json_file = _env_bool(
            "KG_LOG_JSON",
            True,
        )
        max_bytes = int(
            os.getenv(
                "KG_LOG_MAX_BYTES",
                str(DEFAULT_LOG_MAX_BYTES),
            )
        )
        backup_count = int(
            os.getenv(
                "KG_LOG_BACKUP_COUNT",
                str(DEFAULT_LOG_BACKUP_COUNT),
            )
        )

    return {
        "log_dir": log_dir,
        "log_file": log_file,
        "level": str(level).upper(),
        "to_console": bool(to_console),
        "to_file": bool(to_file),
        "json_file": bool(json_file),
        "max_bytes": int(max_bytes),
        "backup_count": int(backup_count),
    }


def get_log_file_path() -> Path:
    """获取日志文件完整路径。"""
    settings = _load_config()
    log_dir = Path(settings["log_dir"])
    log_file = Path(settings["log_file"])

    if not log_dir.is_absolute():
        try:
            from kg_builder import config
            log_dir = (
                config.PROJECT_ROOT
                / log_dir
            ).resolve()
        except Exception:
            log_dir = (
                Path.cwd()
                / log_dir
            ).resolve()

    if log_file.is_absolute():
        return log_file

    return log_dir / log_file


def _level_from_name(level_name: str) -> int:
    level = getattr(
        logging,
        level_name.upper(),
        None,
    )

    if not isinstance(level, int):
        raise ValueError(
            f"无效日志级别：{level_name}"
        )

    return level


def configure_logging(
    *,
    level: Optional[str] = None,
    log_dir: Optional[Path | str] = None,
    log_file: Optional[str] = None,
    to_console: Optional[bool] = None,
    to_file: Optional[bool] = None,
    json_file: Optional[bool] = None,
    max_bytes: Optional[int] = None,
    backup_count: Optional[int] = None,
    force: bool = False,
) -> logging.Logger:
    """
    初始化 KG Builder 日志系统。

    可重复调用；默认不会重复添加 Handler。
    """
    global _configured

    with _config_lock:
        settings = _load_config()

        if level is not None:
            settings["level"] = level.upper()
        if log_dir is not None:
            settings["log_dir"] = Path(log_dir)
        if log_file is not None:
            settings["log_file"] = log_file
        if to_console is not None:
            settings["to_console"] = to_console
        if to_file is not None:
            settings["to_file"] = to_file
        if json_file is not None:
            settings["json_file"] = json_file
        if max_bytes is not None:
            settings["max_bytes"] = max_bytes
        if backup_count is not None:
            settings["backup_count"] = backup_count

        logger = logging.getLogger(
            LOGGER_NAME
        )

        if _configured and not force:
            return logger

        if force:
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass

        logger.setLevel(
            _level_from_name(
                settings["level"]
            )
        )
        logger.propagate = False

        formatter = ConsoleFormatter()

        if settings["to_console"]:
            console = logging.StreamHandler()
            console.setLevel(
                _level_from_name(
                    settings["level"]
                )
            )
            console.setFormatter(formatter)
            console.name = (
                "kg_builder_console"
            )
            logger.addHandler(console)

        if settings["to_file"]:
            path = (
                Path(settings["log_dir"])
            )

            if not path.is_absolute():
                try:
                    from kg_builder import config
                    path = (
                        config.PROJECT_ROOT
                        / path
                    ).resolve()
                except Exception:
                    path = (
                        Path.cwd()
                        / path
                    ).resolve()

            path.mkdir(
                parents=True,
                exist_ok=True,
            )

            file_path = path / str(
                settings["log_file"]
            )

            if Path(
                settings["log_file"]
            ).is_absolute():
                file_path = Path(
                    settings["log_file"]
                )

            file_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            file_handler = RotatingFileHandler(
                file_path,
                maxBytes=settings[
                    "max_bytes"
                ],
                backupCount=settings[
                    "backup_count"
                ],
                encoding="utf-8",
            )
            file_handler.setLevel(
                _level_from_name(
                    settings["level"]
                )
            )

            file_handler.setFormatter(
                JsonFormatter()
                if settings["json_file"]
                else formatter
            )
            file_handler.name = (
                "kg_builder_file"
            )
            logger.addHandler(file_handler)

        _configured = True

        return logger


def get_logger(
    name: Optional[str] = None,
) -> logging.Logger:
    """获取 KG Builder Logger。"""
    configure_logging()

    if not name:
        return logging.getLogger(
            LOGGER_NAME
        )

    if name == LOGGER_NAME or name.startswith(
        LOGGER_NAME + "."
    ):
        return logging.getLogger(name)

    return logging.getLogger(
        f"{LOGGER_NAME}.{name}"
    )


# ============================================================
# Runtime Event logging
# ============================================================


def log_runtime_event(event: Any) -> None:
    """将 RuntimeEvent 写入统一日志。"""
    logger = get_logger(
        "runtime"
    )

    metadata = getattr(
        event,
        "metadata",
        {},
    ) or {}

    level_name = "INFO"

    if getattr(event, "status", None) == "error":
        level_name = "ERROR"
    elif getattr(event, "status", None) == "running":
        level_name = "INFO"

    level = getattr(
        logging,
        level_name,
    )

    logger.log(
        level,
        getattr(
            event,
            "message",
            None,
        )
        or getattr(
            event,
            "event_type",
            "Runtime event",
        ),
        extra={
            "event_type": getattr(
                event,
                "event_type",
                None,
            ),
            "status": getattr(
                event,
                "status",
                None,
            ),
            "run_id": getattr(
                event,
                "run_id",
                None,
            ),
            "stage": getattr(
                event,
                "stage",
                None,
            ),
            "agent": getattr(
                event,
                "agent",
                None,
            ),
            "duration_ms": getattr(
                event,
                "duration_ms",
                None,
            ),
            "structured": redact_mapping(
                metadata
            ),
        },
    )


# ============================================================
# Generic operation decorator
# ============================================================


def _extract_runtime_identity(
    args: tuple,
    kwargs: Dict[str, Any],
) -> Dict[str, Any]:
    """从方法参数或 self 提取 run/stage/agent 信息。"""
    values: Dict[str, Any] = {}

    for key in (
        "run_id",
        "stage",
        "agent",
    ):
        if kwargs.get(key) is not None:
            values[key] = kwargs[key]

    if args:
        self = args[0]
        for key in (
            "run_id",
            "stage",
            "agent_name",
        ):
            if key not in values:
                value = getattr(
                    self,
                    key,
                    None,
                )
                if value is not None:
                    values[
                        "agent"
                        if key == "agent_name"
                        else key
                    ] = value

    return values


def logged_operation(
    operation: Optional[str] = None,
):
    """
    给同步 / 异步业务方法增加结构化日志。

    默认只记录：

        operation
        status
        duration_ms
        run_id
        stage
        agent

    不记录完整参数，避免把用户数据或密钥写入日志。
    """

    def decorator(func):
        operation_name = (
            operation
            or f"{func.__module__}.{func.__qualname__}"
        )

        if inspect.iscoroutinefunction(func):

            async def async_wrapper(
                *args,
                **kwargs,
            ):
                logger = get_logger(
                    func.__module__
                )
                identity = _extract_runtime_identity(
                    args,
                    kwargs,
                )
                started = time.perf_counter()

                logger.info(
                    "Operation started",
                    extra={
                        "operation": operation_name,
                        **identity,
                    },
                )

                try:
                    result = await func(
                        *args,
                        **kwargs,
                    )

                    duration_ms = (
                        time.perf_counter()
                        - started
                    ) * 1000

                    result_status = (
                        result.get("status")
                        if isinstance(
                            result,
                            Mapping,
                        )
                        else "success"
                    )

                    level = (
                        logging.ERROR
                        if result_status == "error"
                        else logging.INFO
                    )

                    logger.log(
                        level,
                        "Operation finished",
                        extra={
                            "operation": operation_name,
                            "status": result_status,
                            "duration_ms": duration_ms,
                            **identity,
                        },
                    )

                    return result

                except Exception as error:
                    duration_ms = (
                        time.perf_counter()
                        - started
                    ) * 1000

                    logger.exception(
                        "Operation failed",
                        extra={
                            "operation": operation_name,
                            "status": "error",
                            "duration_ms": duration_ms,
                            "error_code": getattr(
                                error,
                                "code",
                                None,
                            ),
                            "exception_type": (
                                type(error).__name__
                            ),
                            **identity,
                        },
                    )
                    raise

            async_wrapper.__name__ = func.__name__
            async_wrapper.__qualname__ = func.__qualname__
            async_wrapper.__doc__ = func.__doc__
            async_wrapper.__module__ = func.__module__
            return async_wrapper

        def sync_wrapper(
            *args,
            **kwargs,
        ):
            logger = get_logger(
                func.__module__
            )
            identity = _extract_runtime_identity(
                args,
                kwargs,
            )
            started = time.perf_counter()

            logger.info(
                "Operation started",
                extra={
                    "operation": operation_name,
                    **identity,
                },
            )

            try:
                result = func(
                    *args,
                    **kwargs,
                )

                duration_ms = (
                    time.perf_counter()
                    - started
                ) * 1000

                result_status = (
                    result.get("status")
                    if isinstance(
                        result,
                        Mapping,
                    )
                    else "success"
                )

                level = (
                    logging.ERROR
                    if result_status == "error"
                    else logging.INFO
                )

                logger.log(
                    level,
                    "Operation finished",
                    extra={
                        "operation": operation_name,
                        "status": result_status,
                        "duration_ms": duration_ms,
                        **identity,
                    },
                )

                return result

            except Exception as error:
                duration_ms = (
                    time.perf_counter()
                    - started
                ) * 1000

                logger.exception(
                    "Operation failed",
                    extra={
                        "operation": operation_name,
                        "status": "error",
                        "duration_ms": duration_ms,
                        "error_code": getattr(
                            error,
                            "code",
                            None,
                        ),
                        "exception_type": (
                            type(error).__name__
                        ),
                        **identity,
                    },
                )
                raise

        sync_wrapper.__name__ = func.__name__
        sync_wrapper.__qualname__ = func.__qualname__
        sync_wrapper.__doc__ = func.__doc__
        sync_wrapper.__module__ = func.__module__
        return sync_wrapper

    return decorator


__all__ = [
    "LOGGER_NAME",
    "configure_logging",
    "get_logger",
    "get_log_file_path",
    "get_log_context",
    "set_log_context",
    "reset_log_context",
    "log_context",
    "redact_mapping",
    "query_fingerprint",
    "log_runtime_event",
    "logged_operation",
]
