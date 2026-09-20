"""用户目标：感知 → 批准。"""
from google.adk.tools import ToolContext

from kg_builder.core.neo4j_client import tool_error, tool_success
from kg_builder.state import (
    APPROVED_USER_GOAL,
    PERCEIVED_USER_GOAL,
)


def get_approved_user_goal(tool_context: ToolContext) -> dict:
    if APPROVED_USER_GOAL not in tool_context.state:
        return tool_error(
            "未设置 approved_user_goal。请先让用户确认目标。"
        )
    return tool_success(
        APPROVED_USER_GOAL, tool_context.state[APPROVED_USER_GOAL]
    )


def set_perceived_user_goal(
    kind_of_graph: str, graph_description: str, tool_context: ToolContext
) -> dict:
    """设置'感知的'用户目标（草稿）。"""
    data = {"kind_of_graph": kind_of_graph, "graph_description": graph_description}
    tool_context.state[PERCEIVED_USER_GOAL] = data
    return tool_success(PERCEIVED_USER_GOAL, data)


def approve_perceived_user_goal(tool_context: ToolContext) -> dict:
    """用户确认后，将草稿转为正式批准。"""
    if PERCEIVED_USER_GOAL not in tool_context.state:
        return tool_error("perceived_user_goal 未设置，无法批准。")
    tool_context.state[APPROVED_USER_GOAL] = tool_context.state[
        PERCEIVED_USER_GOAL
    ]
    return tool_success(
        APPROVED_USER_GOAL, tool_context.state[APPROVED_USER_GOAL]
    )