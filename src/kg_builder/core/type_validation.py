"""轻量运行时类型校验工具，弥补工程型 type checking 的最低保障。"""
from __future__ import annotations

from typing import Any, Mapping, Sequence, Type

from kg_builder.core.errors import ConfigurationError, ToolInputError


def require_instance(value: Any, expected: Type[Any] | tuple[Type[Any], ...], name: str) -> Any:
    if not isinstance(value, expected):
        raise ToolInputError(
            f"{name} 类型错误。",
            details={"expected": str(expected), "actual": type(value).__name__},
        )
    return value


def require_mapping(value: Any, name: str = "value") -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ToolInputError(f"{name} 必须是 mapping。")
    return value


def require_sequence(value: Any, name: str = "value") -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ToolInputError(f"{name} 必须是 sequence。")
    return value


def require_positive_number(value: Any, name: str) -> float:
    if not isinstance(value, (int, float)) or value <= 0:
        raise ConfigurationError(f"{name} 必须是正数。")
    return float(value)


__all__ = [
    "require_instance",
    "require_mapping",
    "require_sequence",
    "require_positive_number",
]
