"""
Neo4j 图谱查询引擎。

负责：

    Query Request
        ↓
    Query Validation
        ↓
    Neo4jClient
        ↓
    Result Normalization
        ↓
    Query Report
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from kg_builder.core.errors import QueryExecutionError, QueryValidationError
from kg_builder.core.neo4j_client import graphdb
from kg_builder.core.logger import logged_operation, query_fingerprint


class QueryEngine:
    """负责执行 Neo4j 查询并统一处理查询结果。"""

    def __init__(self, neo4j_client=None):
        self.graphdb = neo4j_client or graphdb
        self.status = "idle"
        self.report: Dict[str, Any] = self._empty_report()

    @staticmethod
    def _empty_report() -> Dict[str, Any]:
        return {
            "status": "idle",
            "query": None,
            "parameters": {},
            "result_count": 0,
            "result": [],
            "error_message": None,
        }

    @staticmethod
    def _normalize_parameters(parameters: Optional[dict]) -> Dict[str, Any]:
        if parameters is None:
            return {}
        if not isinstance(parameters, dict):
            raise QueryValidationError("parameters 必须是 dict 或 None。")
        return dict(parameters)

    def validate_query(
        self,
        cypher: str,
        parameters: Optional[dict] = None,
    ) -> Dict[str, Any]:
        errors = []

        if not isinstance(cypher, str):
            errors.append("cypher 必须是字符串。")
        elif not cypher.strip():
            errors.append("cypher 不能为空。")

        if parameters is not None and not isinstance(parameters, dict):
            errors.append("parameters 必须是 dict 或 None。")

        return {
            "valid": not errors,
            "errors": errors,
        }

    def normalize_result(
        self,
        result: Optional[Dict[str, Any]],
        cypher: str,
        parameters: Optional[dict] = None,
    ) -> Dict[str, Any]:
        parameters = self._normalize_parameters(parameters)

        if not isinstance(result, dict):
            return {
                "status": "error",
                "query": cypher,
                "parameters": parameters,
                "result_count": 0,
                "result": [],
                "error_message": "Neo4jClient 返回了无效的结果格式。",
            }

        if result.get("status") != "success":
            return {
                "status": "error",
                "query": cypher,
                "parameters": parameters,
                "result_count": 0,
                "result": [],
                "error_message": result.get(
                    "error_message",
                    "Neo4j 查询失败。",
                ),
            }

        query_result = result.get("query_result", []) or []

        if not isinstance(query_result, list):
            query_result = list(query_result)

        return {
            "status": "success",
            "query": cypher,
            "parameters": parameters,
            "result_count": len(query_result),
            "result": query_result,
            "error_message": None,
        }

    @logged_operation("query.query")
    def query(
        self,
        cypher: str,
        parameters: Optional[dict] = None,
    ) -> Dict[str, Any]:
        validation = self.validate_query(cypher, parameters)

        if not validation["valid"]:
            error_message = "; ".join(validation["errors"])
            self.status = "error"
            self.report = {
                "status": "error",
                "query": cypher if isinstance(cypher, str) else None,
                "parameters": parameters if isinstance(parameters, dict) else {},
                "result_count": 0,
                "result": [],
                "error_message": error_message,
            }
            return dict(self.report)

        normalized_cypher = cypher.strip()
        normalized_parameters = self._normalize_parameters(parameters)

        self.status = "running"

        try:
            result = self.graphdb.send_query(
                normalized_cypher,
                normalized_parameters,
            )

            normalized = self.normalize_result(
                result=result,
                cypher=normalized_cypher,
                parameters=normalized_parameters,
            )

            self.status = normalized["status"]
            self.report = normalized
            return dict(normalized)

        except QueryExecutionError as error:
            self.status = "error"
            self.report = {
                "status": "error",
                "query": normalized_cypher,
                "parameters": normalized_parameters,
                "result_count": 0,
                "result": [],
                "error_message": str(error),
                "error_code": error.code,
                "error_type": error.__class__.__name__,
            }
            return dict(self.report)

        except Exception as error:
            wrapped = QueryExecutionError.from_exception(
                error,
                message="Query 执行失败。",
            )
            self.status = "error"
            self.report = {
                "status": "error",
                "query": normalized_cypher,
                "parameters": normalized_parameters,
                "result_count": 0,
                "result": [],
                "error_message": str(wrapped),
                "error_code": wrapped.code,
                "error_type": wrapped.__class__.__name__,
            }
            return dict(self.report)

    def get_report(self) -> Dict[str, Any]:
        return dict(self.report)

    def reset(self) -> None:
        self.status = "idle"
        self.report = self._empty_report()


__all__ = ["QueryEngine"]
