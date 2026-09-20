"""结构化图谱：提议/移除节点与关系构建。"""
from google.adk.tools import ToolContext

from kg_builder.core.neo4j_client import tool_error, tool_success
from kg_builder.state import PROPOSED_CONSTRUCTION_PLAN
from kg_builder.tools.file_tools import search_file


def get_proposed_construction_plan(tool_context: ToolContext) -> dict:
    return tool_context.state.get(PROPOSED_CONSTRUCTION_PLAN, {})


def propose_node_construction(
    approved_file: str,
    proposed_label: str,
    unique_column_name: str,
    proposed_properties: list,
    tool_context: ToolContext,
) -> dict:
    result = search_file(approved_file, unique_column_name)
    if result["status"] == "error":
        return result
    if result["search_results"]["metadata"]["lines_found"] == 0:
        return tool_error(
            f"{approved_file} 中不存在列 {unique_column_name}"
        )

    plan = tool_context.state.get(PROPOSED_CONSTRUCTION_PLAN, {})
    rule = {
        "construction_type": "node",
        "source_file": approved_file,
        "label": proposed_label,
        "unique_column_name": unique_column_name,
        "properties": proposed_properties,
    }
    plan[proposed_label] = rule
    tool_context.state[PROPOSED_CONSTRUCTION_PLAN] = plan
    return tool_success("node_construction", rule)


def propose_relationship_construction(
    approved_file: str,
    proposed_relationship_type: str,
    from_node_label: str,
    from_node_column: str,
    to_node_label: str,
    to_node_column: str,
    proposed_properties: list,
    tool_context: ToolContext,
) -> dict:
    for col in (from_node_column, to_node_column):
        r = search_file(approved_file, col)
        if r["status"] == "error":
            return r
        if r["search_results"]["metadata"]["lines_found"] == 0:
            return tool_error(f"{approved_file} 中不存在列 {col}")

    plan = tool_context.state.get(PROPOSED_CONSTRUCTION_PLAN, {})
    rule = {
        "construction_type": "relationship",
        "source_file": approved_file,
        "relationship_type": proposed_relationship_type,
        "from_node_label": from_node_label,
        "from_node_column": from_node_column,
        "to_node_label": to_node_label,
        "to_node_column": to_node_column,
        "properties": proposed_properties,
    }
    plan[proposed_relationship_type] = rule
    tool_context.state[PROPOSED_CONSTRUCTION_PLAN] = plan
    return tool_success("relationship_construction", rule)


def remove_node_construction(node_label: str, tool_context: ToolContext) -> dict:
    plan = tool_context.state.get(PROPOSED_CONSTRUCTION_PLAN, {})
    if node_label not in plan:
        return tool_success("message", "未找到该节点构建规则，无需移除。")
    del plan[node_label]
    tool_context.state[PROPOSED_CONSTRUCTION_PLAN] = plan
    return tool_success("node_construction_removed", node_label)


def remove_relationship_construction(
    relationship_type: str, tool_context: ToolContext
) -> dict:
    plan = tool_context.state.get(PROPOSED_CONSTRUCTION_PLAN, {})
    if relationship_type not in plan:
        return tool_success("message", "未找到该关系构建规则，无需移除。")
    plan.pop(relationship_type)
    tool_context.state[PROPOSED_CONSTRUCTION_PLAN] = plan
    return tool_success("relationship_construction_removed", relationship_type)