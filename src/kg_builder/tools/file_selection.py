"""文件选择工具：拆分为"结构化"和"非结构化"两套。

状态键：
    结构化：
        - suggested_structured_files
        - approved_structured_files
    非结构化：
        - suggested_unstructured_files
        - approved_unstructured_files
    兼容（旧）：
        - suggested_files / approved_files
"""

from typing import Any, Dict, List

from google.adk.tools import ToolContext

from kg_builder.core.neo4j_client import tool_error, tool_success
from kg_builder.state import (
    APPROVED_FILES,
    APPROVED_STRUCTURED_FILES,
    APPROVED_UNSTRUCTURED_FILES,
    SUGGESTED_FILES,
    SUGGESTED_STRUCTURED_FILES,
    SUGGESTED_UNSTRUCTURED_FILES,
)
from kg_builder.tools.file_tools import list_available_files  # noqa: F401


# ============================================================
# 一、结构化文件工具
# ============================================================

def set_suggested_structured_files(
    suggest_files: List[str],
    tool_context: ToolContext,
) -> dict:
    """设置"建议的结构化文件"列表（CSV / JSON）。

    Args:
        suggest_files: 建议的文件相对路径列表
    """
    if not suggest_files:
        return tool_error(
            "传入的结构化文件列表为空！请先调用 list_available_files。"
        )

    # 只保留 .csv / .json / .parquet / .xlsx
    valid_exts = (".csv", ".json", ".parquet", ".xlsx")
    cleaned = [
        f for f in suggest_files
        if isinstance(f, str) and f.lower().endswith(valid_exts)
    ]
    if not cleaned:
        return tool_error(
            "传入的文件没有 .csv/.json 类型。请检查后重试。"
        )

    tool_context.state[SUGGESTED_STRUCTURED_FILES] = cleaned
    return tool_success(SUGGESTED_STRUCTURED_FILES, cleaned)


def get_suggested_structured_files(tool_context: ToolContext) -> dict:
    files = tool_context.state.get(SUGGESTED_STRUCTURED_FILES, [])
    if not files:
        return tool_error("尚未设置结构化建议文件。")
    return tool_success(SUGGESTED_STRUCTURED_FILES, files)


def approve_suggested_structured_files(tool_context: ToolContext) -> dict:
    """把"建议的结构化文件"转为"已批准"。"""
    if SUGGESTED_STRUCTURED_FILES not in tool_context.state:
        return tool_error("没有可批准的结构化文件建议。")

    approved = list(tool_context.state[SUGGESTED_STRUCTURED_FILES])
    tool_context.state[APPROVED_STRUCTURED_FILES] = approved
    return tool_success(APPROVED_STRUCTURED_FILES, approved)


def get_approved_structured_files(tool_context: ToolContext) -> dict:
    files = tool_context.state.get(APPROVED_STRUCTURED_FILES, [])
    if not files:
        return tool_error(
            "尚未批准任何结构化文件。请先推荐并批准。"
        )
    return tool_success(APPROVED_STRUCTURED_FILES, files)


# ============================================================
# 二、非结构化文件工具
# ============================================================

def set_suggested_unstructured_files(
    suggest_files: List[str],
    tool_context: ToolContext,
) -> dict:
    """设置"建议的非结构化文件"列表（MD / TXT）。"""
    if not suggest_files:
        return tool_error(
            "传入的非结构化文件列表为空！请先调用 list_available_files。"
        )

    valid_exts = (".md", ".markdown", ".txt", ".pdf")
    cleaned = [
        f for f in suggest_files
        if isinstance(f, str) and f.lower().endswith(valid_exts)
    ]
    if not cleaned:
        return tool_error(
            "传入的文件没有 .md/.txt 类型。请检查后重试。"
        )

    tool_context.state[SUGGESTED_UNSTRUCTURED_FILES] = cleaned
    return tool_success(SUGGESTED_UNSTRUCTURED_FILES, cleaned)


def get_suggested_unstructured_files(tool_context: ToolContext) -> dict:
    files = tool_context.state.get(SUGGESTED_UNSTRUCTURED_FILES, [])
    if not files:
        return tool_error("尚未设置非结构化建议文件。")
    return tool_success(SUGGESTED_UNSTRUCTURED_FILES, files)


def approve_suggested_unstructured_files(tool_context: ToolContext) -> dict:
    if SUGGESTED_UNSTRUCTURED_FILES not in tool_context.state:
        return tool_error("没有可批准的非结构化文件建议。")

    approved = list(tool_context.state[SUGGESTED_UNSTRUCTURED_FILES])
    tool_context.state[APPROVED_UNSTRUCTURED_FILES] = approved
    return tool_success(APPROVED_UNSTRUCTURED_FILES, approved)


def get_approved_unstructured_files(tool_context: ToolContext) -> dict:
    files = tool_context.state.get(APPROVED_UNSTRUCTURED_FILES, [])
    if not files:
        return tool_error(
            "尚未批准任何非结构化文件。请先推荐并批准。"
        )
    return tool_success(APPROVED_UNSTRUCTURED_FILES, files)


# ============================================================
# 三、兼容工具（旧接口，保留但不推荐）
# ============================================================

def get_approved_files(tool_context: ToolContext) -> dict:
    """兼容：返回合并版已批准文件。"""
    if APPROVED_FILES not in tool_context.state:
        return tool_error("未设置 approved_files。")
    return tool_success(APPROVED_FILES, tool_context.state[APPROVED_FILES])


def sync_merged_approved_files(tool_context: ToolContext) -> None:
    """把两个分类列表合并写入 approved_files（兼容旧逻辑）。

    在 approve_*_structured_files 和 approve_*_unstructured_files
    之后由调用方显式触发，或者由 pipeline 自动调用。
    """
    s = tool_context.state.get(APPROVED_STRUCTURED_FILES, [])
    u = tool_context.state.get(APPROVED_UNSTRUCTURED_FILES, [])
    tool_context.state[APPROVED_FILES] = list(s) + list(u)