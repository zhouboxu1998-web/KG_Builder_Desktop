"""非结构化图谱 - 实体类型（Entity Type）工具集。

本模块为 NER Agent（`agents/ner_agent.py`）提供 5 个工具：

    写入类：
        - set_proposed_entities      保存"建议实体类型"草稿
        - approve_proposed_entities  用户批准后，草稿转正

    读取类：
        - get_proposed_entities      读取草稿（用于展示给用户）
        - get_approved_entities      读取最终批准结果（供下游 Fact Agent 使用）
        - get_well_known_types       读取已有图谱 schema 中的节点标签（用于复用）

状态键（定义于 kg_builder.state）：
    PROPOSED_ENTITIES      = "proposed_entity_types"
    APPROVED_ENTITIES      = "approved_entity_types"
    APPROVED_CONSTRUCTION_PLAN = "approved_construction_plan"
"""

from typing import Any, Dict, List

from google.adk.tools import ToolContext

from kg_builder.core.neo4j_client import tool_error, tool_success
from kg_builder.state import (
    APPROVED_CONSTRUCTION_PLAN,
    APPROVED_ENTITIES,
    PROPOSED_ENTITIES,
)


# ============================================================
# 一、写入类工具
# ============================================================

def set_proposed_entities(
    proposed_entity_types: List[str],
    tool_context: ToolContext,
) -> Dict[str, Any]:
    """设置准备从非结构化文本中提取的"建议实体类型"列表。

    这个工具**只写草稿**，不代表这些类型已被批准。用户需要显式批准
    （`approve_proposed_entities`）之后，它们才会进入"已批准"状态。

    Args:
        proposed_entity_types: 建议的实体类型名称列表，例如
            ``["Product", "Part", "Assembly", "Review", "Reviewer", "Issue"]``。
        tool_context: ADK 注入的工具上下文，提供对 session.state 的读写权限。

    Returns:
        成功时返回 ``{"status": "success", "proposed_entity_types": [...]}``。
    """
    # 简单的输入规范化：去重、去空白、去空字符串
    # （LLM 有时会给出 ['Product', 'Product', ' Part '] 之类的重复/脏数据）
    cleaned: List[str] = []
    seen = set()
    for name in proposed_entity_types or []:
        if not isinstance(name, str):
            continue
        n = name.strip()
        if not n or n in seen:
            continue
        seen.add(n)
        cleaned.append(n)

    if not cleaned:
        return tool_error(
            "建议实体类型列表为空。请先调用 sample_file 阅读文件内容，"
            "再基于文本给出实体类型建议。"
        )

    tool_context.state[PROPOSED_ENTITIES] = cleaned
    return tool_success(PROPOSED_ENTITIES, cleaned)


def approve_proposed_entities(tool_context: ToolContext) -> Dict[str, Any]:
    """在用户批准后，将"建议实体类型"记录为"已批准实体类型"。

    ⚠️ 只有用户明确表示同意（例如："批准这些实体"、"OK"、"同意"）时，
    才应该调用本工具。

    如果 state 中没有 ``proposed_entity_types``，说明 NER Agent 还没有
    提议过任何实体，此时直接报错，让 LLM 回到正确的步骤。

    Args:
        tool_context: ADK 工具上下文。

    Returns:
        成功时返回 ``{"status": "success", "approved_entity_types": [...]}``；
        失败时返回 ``{"status": "error", "error_message": "..."}``。
    """
    if PROPOSED_ENTITIES not in tool_context.state:
        return tool_error(
            "没有可批准的建议实体类型。请先使用 set_proposed_entities "
            "设置建议，展示给用户确认，再调用本工具。"
        )

    proposed = tool_context.state.get(PROPOSED_ENTITIES, [])
    if not proposed:
        return tool_error("建议实体类型列表为空，无法批准。")

    # 转正：草稿 → 正式
    tool_context.state[APPROVED_ENTITIES] = list(proposed)
    return tool_success(APPROVED_ENTITIES, tool_context.state[APPROVED_ENTITIES])


# ============================================================
# 二、读取类工具
# ============================================================

def get_proposed_entities(tool_context: ToolContext) -> Dict[str, Any]:
    """获取当前的"建议实体类型"列表（尚未批准）。

    该工具返回 ``{"status": "success", "proposed_entity_types": [...]}``，
    若 state 中没有该键，则返回空列表（status 仍为 success）。

    Args:
        tool_context: ADK 工具上下文。

    Returns:
        成功时始终返回一个带 ``proposed_entity_types`` 列表的字典。
    """
    proposed = tool_context.state.get(PROPOSED_ENTITIES, [])
    return tool_success(PROPOSED_ENTITIES, list(proposed))


def get_approved_entities(tool_context: ToolContext) -> Dict[str, Any]:
    """获取最终批准的、将从非结构化文本中提取的"实体类型"列表。

    下游的 Fact Agent 使用本工具来获取"主语/宾语的白名单"，
    以此校验它建议的三元组是否合法。

    Args:
        tool_context: ADK 工具上下文。

    Returns:
        成功时返回 ``{"status": "success", "approved_entity_types": [...]}``。
        若尚未批准任何实体，返回空列表（status 仍为 success）。
    """
    approved = tool_context.state.get(APPROVED_ENTITIES, [])
    return tool_success(APPROVED_ENTITIES, list(approved))


def get_well_known_types(tool_context: ToolContext) -> Dict[str, Any]:
    """获取"已有图谱 schema"中已批准的节点标签（即已知实体类型）。

    逻辑：
        1. 从 state 中读取 ``approved_construction_plan``（结构化图谱阶段
           由 schema_proposal_agent / schema_critic_agent 写入）；
        2. 从中筛选出 ``construction_type == "node"`` 的条目；
        3. 提取它们的 ``label`` 字段，去重后返回。

    用途：
        NER Agent 在提议新实体时，应优先**复用**这些已知标签，
        而不是凭空发明新类型，从而保证与已有图谱的兼容性。

    Args:
        tool_context: ADK 工具上下文。

    Returns:
        成功时返回 ``{"status": "success", "approved_labels": [str, ...]}``。
        若 state 中没有 ``approved_construction_plan``，返回空列表
        （这是合法降级，不视为错误）。
    """
    plan = tool_context.state.get(APPROVED_CONSTRUCTION_PLAN, {}) or {}

    labels = {
        entry["label"]
        for entry in plan.values()
        if isinstance(entry, dict)
        and entry.get("construction_type") == "node"
        and entry.get("label")
    }

    # 排序后返回，保证多次调用的输出稳定（便于 LLM 缓存与人类对照）
    return tool_success("approved_labels", sorted(labels))


# ============================================================
# 三、导出工具列表（供 Agent 直接引用）
# ============================================================

# NER Agent 需要的完整工具集（顺序无关，仅作打包便利）
ENTITY_TOOLS = [
    set_proposed_entities,
    approve_proposed_entities,
    get_proposed_entities,
    get_approved_entities,
    get_well_known_types,
]


__all__ = [
    # 写入类
    "set_proposed_entities",
    "approve_proposed_entities",
    # 读取类
    "get_proposed_entities",
    "get_approved_entities",
    "get_well_known_types",
    # 打包列表
    "ENTITY_TOOLS",
]