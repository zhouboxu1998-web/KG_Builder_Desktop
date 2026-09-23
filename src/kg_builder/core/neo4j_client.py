"""Neo4j 客户端，返回 ADK 友好的字典格式。"""
from typing import Any, Dict, List, Optional

import neo4j.time
from neo4j import GraphDatabase, Record, Result
from neo4j.graph import Node, Path, Relationship

from kg_builder import config
from kg_builder.core.errors import (
    KGBuilderError,
    Neo4jConnectionError,
    Neo4jQueryError,
)
from kg_builder.core.logger import logged_operation, get_logger, query_fingerprint

logger = get_logger(__name__)


def tool_success(key: str, result: Any) -> Dict[str, Any]:
    return {"status": "success", key: result}


def tool_error(
    message: str,
    error: Optional[KGBuilderError] = None,
) -> Dict[str, Any]:
    """构造兼容旧接口的结构化 Neo4j 错误。"""

    payload: Dict[str, Any] = {
        "status": "error",
        "error_message": message,
    }

    if error is not None:
        payload.update(
            {
                "error_code": error.code,
                "error_type": error.__class__.__name__,
                "error_details": dict(error.details),
            }
        )

    return payload


def _to_python(value: Any) -> Any:
    if isinstance(value, Record):
        return {k: _to_python(v) for k, v in value.items()}
    if isinstance(value, dict):
        return {k: _to_python(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_python(v) for v in value]
    if isinstance(value, Node):
        return {
            "id": value.id,
            "labels": list(value.labels),
            "properties": _to_python(dict(value)),
        }
    if isinstance(value, Relationship):
        return {
            "id": value.id,
            "type": value.type,
            "start_node": value.start_node.id,
            "end_node": value.end_node.id,
            "properties": _to_python(dict(value)),
        }
    if isinstance(value, Path):
        return {
            "nodes": [_to_python(n) for n in value.nodes],
            "relationships": [_to_python(r) for r in value.relationships],
        }
    if isinstance(value, neo4j.time.DateTime):
        return value.iso_format()
    if isinstance(value, (neo4j.time.Date, neo4j.time.Time, neo4j.time.Duration)):
        return str(value)
    return value


class Neo4jClient:
    """线程安全的 Neo4j 客户端（懒加载 driver）。"""

    _driver = None

    def __init__(self):
        self.database = config.NEO4J_DATABASE

    def _ensure_driver(self):
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                config.NEO4J_URI,
                auth=(
                    config.NEO4J_USERNAME,
                    config.NEO4J_PASSWORD,
                ),
                connection_timeout=(
                    config.NEO4J_CONNECTION_TIMEOUT_SECONDS
                ),
            )
        return self._driver

    def get_driver(self):
        return self._ensure_driver()

    def close(self):
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    @logged_operation("neo4j.send_query")
    def send_query(
        self, cypher: str, parameters: Optional[dict] = None
    ) -> Dict[str, Any]:
        logger.debug(
            "Neo4j query requested",
            extra={
                "query_fingerprint": query_fingerprint(cypher),
                "structured": {
                    "parameter_keys": list((parameters or {}).keys()),
                },
            },
        )

        try:
            driver = self._ensure_driver()
        except Exception as error:
            wrapped = Neo4jConnectionError.from_exception(
                error,
                message="Neo4j Driver 初始化失败。",
            )
            return tool_error(
                str(wrapped),
                wrapped,
            )

        try:
            session = driver.session()
        except Exception as error:
            wrapped = Neo4jConnectionError.from_exception(
                error,
                message="Neo4j Session 创建失败。",
            )
            return tool_error(
                str(wrapped),
                wrapped,
            )

        try:
            result: Result = session.run(
                cypher, parameters or {}, database_=self.database
            )
            eager = result.to_eager_result()
            records = [_to_python(r.data()) for r in eager.records]
            return tool_success("query_result", records)
        except Exception as error:
            wrapped = Neo4jQueryError.from_exception(
                error,
                message="Neo4j Cypher 执行失败。",
                details={"query": cypher},
            )
            return tool_error(
                str(wrapped),
                wrapped,
            )
        finally:
            session.close()

    def ping(self) -> bool:
        r = self.send_query("RETURN 1 AS ok")
        return r.get("status") == "success"

    def check_connection(self) -> Dict[str, Any]:
        """供 UI 健康检查使用。

        与 ping() 不同，本方法返回 app.py 期望的字典格式：

            {"connected": True}
            {"connected": False, "error_code": ..., "error_message": ...}
        """
        result = self.send_query("RETURN 1 AS ok")

        if result.get("status") == "success":
            return {"connected": True}

        return {
            "connected": False,
            "error_code": result.get(
                "error_code",
                "NEO4J_ERROR",
            ),
            "error_message": result.get(
                "error_message",
                "Neo4j 连接失败。",
            ),
        }


graphdb = Neo4jClient()