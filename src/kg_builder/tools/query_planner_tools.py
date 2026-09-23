"""Query Planner / Entity Linking 的 ADK 工具。"""
from __future__ import annotations

from typing import Any, Dict

from google.adk.tools import ToolContext

from kg_builder.core.query_planner import QueryPlanner
from kg_builder.core.neo4j_client import graphdb, tool_error, tool_success


def inspect_graph_schema(tool_context: ToolContext) -> Dict[str, Any]:
    """读取当前图谱的节点标签和关系类型。

    结果写入 query_schema，供 Query Agent 后续 Cypher 生成使用。
    """
    try:
        schema = QueryPlanner(graphdb).inspect_schema()
        tool_context.state["query_schema"] = schema
        return tool_success("query_schema", schema)
    except Exception as error:
        return tool_error(f"读取图谱 Schema 失败：{error}")


def find_entity_candidates(
    text: str,
    candidates: list[str],
    tool_context: ToolContext,
) -> Dict[str, Any]:
    """从给定候选名称中查找与用户实体最匹配的候选。"""
    if not isinstance(text, str) or not text.strip():
        return tool_error("text 不能为空。")
    result = QueryPlanner.link_entity(text, candidates)
    tool_context.state["query_entity_candidates"] = result
    return tool_success("query_entity_candidates", result)


QUERY_PLANNER_TOOLS = [
    inspect_graph_schema,
    find_entity_candidates,
]

__all__ = [
    "inspect_graph_schema",
    "find_entity_candidates",
    "QUERY_PLANNER_TOOLS",
]
