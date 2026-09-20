"""Neo4j 客户端，返回 ADK 友好的字典格式。"""
from typing import Any, Dict, List, Optional

import neo4j.time
from neo4j import GraphDatabase, Record, Result
from neo4j.graph import Node, Path, Relationship

from kg_builder import config


def tool_success(key: str, result: Any) -> Dict[str, Any]:
    return {"status": "success", key: result}


def tool_error(message: str) -> Dict[str, Any]:
    return {"status": "error", "error_message": message}


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
        self.database = (
            config.__dict__.get("NEO4J_DATABASE")
            or __import__("os").getenv("NEO4J_DATABASE")
            or __import__("os").getenv("NEO4J_USERNAME")
            or "neo4j"
        )

    def _ensure_driver(self):
        if self._driver is None:
            import os
            self._driver = GraphDatabase.driver(
                os.getenv("NEO4J_URI"),
                auth=(os.getenv("NEO4J_USERNAME", "neo4j"),
                      os.getenv("NEO4J_PASSWORD")),
            )
        return self._driver

    def get_driver(self):
        return self._ensure_driver()

    def close(self):
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def send_query(
        self, cypher: str, parameters: Optional[dict] = None
    ) -> Dict[str, Any]:
        session = self._ensure_driver().session()
        try:
            result: Result = session.run(
                cypher, parameters or {}, database_=self.database
            )
            eager = result.to_eager_result()
            records = [_to_python(r.data()) for r in eager.records]
            return tool_success("query_result", records)
        except Exception as e:
            return tool_error(str(e))
        finally:
            session.close()

    def ping(self) -> bool:
        r = self.send_query("RETURN 1 AS ok")
        return r.get("status") == "success"


graphdb = Neo4jClient()