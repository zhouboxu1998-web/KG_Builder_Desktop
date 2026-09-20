"""事实类型：建议 → 批准。"""
from google.adk.tools import ToolContext

from kg_builder.core.neo4j_client import tool_error, tool_success
from kg_builder.state import (
    APPROVED_ENTITIES,
    APPROVED_FACTS,
    PROPOSED_FACTS,
)


def add_proposed_fact(
    approved_subject_label: str,
    proposed_predicate_label: str,
    approved_object_label: str,
    tool_context: ToolContext,
) -> dict:
    approved = tool_context.state.get(APPROVED_ENTITIES, [])
    if approved_subject_label not in approved:
        return tool_error(
            f"主语 {approved_subject_label} 不在已批准实体列表中。"
        )
    if approved_object_label not in approved:
        return tool_error(
            f"宾语 {approved_object_label} 不在已批准实体列表中。"
        )

    facts = tool_context.state.get(PROPOSED_FACTS, {})
    facts[proposed_predicate_label] = {
        "subject_label": approved_subject_label,
        "predicate_label": proposed_predicate_label,
        "object_label": approved_object_label,
    }
    tool_context.state[PROPOSED_FACTS] = facts
    return tool_success(PROPOSED_FACTS, facts)


def get_proposed_facts(tool_context: ToolContext) -> dict:
    return tool_success(
        PROPOSED_FACTS, tool_context.state.get(PROPOSED_FACTS, {})
    )


def approve_proposed_facts(tool_context: ToolContext) -> dict:
    if PROPOSED_FACTS not in tool_context.state:
        return tool_error("没有可批准的事实类型。")
    tool_context.state[APPROVED_FACTS] = tool_context.state[PROPOSED_FACTS]
    return tool_success(APPROVED_FACTS, tool_context.state[APPROVED_FACTS])