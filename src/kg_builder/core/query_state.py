"""
Query 阶段状态模型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from kg_builder.core.errors import QueryValidationError

from kg_builder.state import (
    QUERY_CYPHER,
    QUERY_ERROR,
    QUERY_PARAMETERS,
    QUERY_REPORT,
    QUERY_RESULT,
    QUERY_RESULT_COUNT,
    QUERY_STATUS,
)


@dataclass
class QueryState:
    """保存一次 Query 运行的标准化状态。"""

    status: str = "idle"
    cypher: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    result: List[Any] = field(default_factory=list)
    result_count: int = 0
    error_message: Optional[str] = None
    report: Dict[str, Any] = field(default_factory=dict)

    VALID_STATUSES = {
        "idle",
        "running",
        "success",
        "error",
    }

    def reset(self) -> None:
        self.status = "idle"
        self.cypher = None
        self.parameters = {}
        self.result = []
        self.result_count = 0
        self.error_message = None
        self.report = {}

    def update_from_report(
        self,
        report: Optional[Dict[str, Any]],
    ) -> "QueryState":
        if report is None:
            report = {}

        if not isinstance(report, dict):
            raise QueryValidationError("report 必须是 dict 或 None。")

        status = report.get(
            QUERY_STATUS,
            report.get("status", "idle"),
        )

        if status not in self.VALID_STATUSES:
            raise QueryValidationError(f"无效的 Query 状态：{status}。")

        parameters = report.get(
            QUERY_PARAMETERS,
            report.get("parameters", {}),
        ) or {}

        if not isinstance(parameters, dict):
            raise QueryValidationError("query parameters 必须是 dict。")

        result = report.get(
            QUERY_RESULT,
            report.get("result", []),
        ) or []

        if not isinstance(result, list):
            result = list(result)

        result_count = report.get(
            QUERY_RESULT_COUNT,
            len(result),
        )

        self.status = status
        self.cypher = report.get(
            QUERY_CYPHER,
            report.get("query"),
        )
        self.parameters = dict(parameters)
        self.result = list(result)
        self.result_count = int(result_count)
        self.error_message = report.get(
            QUERY_ERROR,
            report.get("error_message"),
        )
        self.report = dict(report)

        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            QUERY_STATUS: self.status,
            QUERY_CYPHER: self.cypher,
            QUERY_PARAMETERS: dict(self.parameters),
            QUERY_RESULT: list(self.result),
            QUERY_RESULT_COUNT: self.result_count,
            QUERY_ERROR: self.error_message,
            QUERY_REPORT: dict(self.report),
        }

    def snapshot(self) -> Dict[str, Any]:
        return self.to_dict()

    def is_running(self) -> bool:
        return self.status == "running"

    def is_success(self) -> bool:
        return self.status == "success"

    def has_error(self) -> bool:
        return self.status == "error"


__all__ = ["QueryState"]
