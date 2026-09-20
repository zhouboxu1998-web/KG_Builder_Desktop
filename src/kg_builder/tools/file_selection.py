"""文件选择：建议 → 获取 → 批准（结构化/非结构化分离版）。"""

from typing import Any, Dict, List

from google.adk.tools import ToolContext

from kg_builder.core.neo4j_client import tool_error, tool_success
from kg_builder.state import APPROVED_FILES, SUGGESTED_FILES
from kg_builder.tools.goal_tools import get_approved_user_goal  # noqa


# 新增状态键
APPROVED_STRUCTURED_FILES = "approved_structured_files"
APPROVED_UNSTRUCTURED_FILES = "approved_unstructured_files"
SUGGESTED_STRUCTURED_FILES = "suggested_structured_files"
SUGGESTED_UNSTRUCTURED_FILES = "suggested_unstructured_files"


STRUCTURED_EXTS = (".csv", ".json", ".parquet", ".xlsx")
UNSTRUCTURED_EXTS = (".md", ".markdown", ".txt", ".pdf")


def _classify(files: List[str]) -> tuple:
    """按后缀分类。"""
    s, u, other = [], [], []
    for f in files:
        fl = f.lower()
        if fl.endswith(STRUCTURED_EXTS):
            s.append(f)
        elif fl.endswith(UNSTRUCTURED_EXTS):
            u.append(f)
        else:
            other.append(f)
    return s, u, other


def set_suggested_files(
    structured_files: List[str],
    unstructured_files: List[str],
    tool_context: ToolContext,
) -> dict:
    """分别设置结构化和非结构化的建议文件。

    Args:
        structured_files: 结构化建议（CSV/JSON）
        unstructured_files: 非结构化建议（MD/TXT）
    """
    if not structured_files and not unstructured_files:
        return tool_error("两个文件列表都为空。请重新推荐。")

    # 合并版（兼容）
    all_files = list(structured_files or []) + list(unstructured_files or [])
    tool_context.state[SUGGESTED_FILES] = all_files

    # 分类版（新增）
    tool_context.state[SUGGESTED_STRUCTURED_FILES] = list(structured_files or [])
    tool_context.state[SUGGESTED_UNSTRUCTURED_FILES] = list(unstructured_files or [])

    return tool_success(SUGGESTED_FILES, {
        "structured": structured_files or [],
        "unstructured": unstructured_files or [],
    })


def get_suggested_files(tool_context: ToolContext) -> Dict[str, Any]:
    return tool_success(SUGGESTED_FILES, {
        "structured": tool_context.state.get(SUGGESTED_STRUCTURED_FILES, []),
        "unstructured": tool_context.state.get(SUGGESTED_UNSTRUCTURED_FILES, []),
    })


def approve_suggested_files(tool_context: ToolContext) -> Dict[str, Any]:
    """批准建议文件，分类转正。"""
    if SUGGESTED_FILES not in tool_context.state:
        return tool_error("没有可批准的建议文件。")

    # 兼容版
    tool_context.state[APPROVED_FILES] = tool_context.state[SUGGESTED_FILES]

    # 分类版
    tool_context.state[APPROVED_STRUCTURED_FILES] = tool_context.state.get(
        SUGGESTED_STRUCTURED_FILES, []
    )
    tool_context.state[APPROVED_UNSTRUCTURED_FILES] = tool_context.state.get(
        SUGGESTED_UNSTRUCTURED_FILES, []
    )

    return tool_success(APPROVED_FILES, {
        "structured": tool_context.state[APPROVED_STRUCTURED_FILES],
        "unstructured": tool_context.state[APPROVED_UNSTRUCTURED_FILES],
    })


# ============================================================
# 新增：分类读取工具
# ============================================================

def get_approved_structured_files(tool_context: ToolContext) -> Dict[str, Any]:
    """获取已批准的结构化文件（CSV / JSON）。"""
    files = tool_context.state.get(APPROVED_STRUCTURED_FILES, [])
    if not files:
        # 兜底：如果分类列表不存在，从合并列表里过滤
        merged = tool_context.state.get(APPROVED_FILES, [])
        files = [f for f in merged if f.lower().endswith(STRUCTURED_EXTS)]
    return tool_success(APPROVED_STRUCTURED_FILES, files)


def get_approved_unstructured_files(tool_context: ToolContext) -> Dict[str, Any]:
    """获取已批准的非结构化文件（MD / TXT）。"""
    files = tool_context.state.get(APPROVED_UNSTRUCTURED_FILES, [])
    if not files:
        merged = tool_context.state.get(APPROVED_FILES, [])
        files = [f for f in merged if f.lower().endswith(UNSTRUCTURED_EXTS)]
    return tool_success(APPROVED_UNSTRUCTURED_FILES, files)


# 兼容：保留原 get_approved_files（合并版）
def get_approved_files(tool_context: ToolContext) -> dict:
    if APPROVED_FILES not in tool_context.state:
        return tool_error("未设置 approved_files。")
    return tool_success(APPROVED_FILES, tool_context.state[APPROVED_FILES])