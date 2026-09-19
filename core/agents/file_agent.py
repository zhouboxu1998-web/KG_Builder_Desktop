from pathlib import Path
from typing import List, Dict, Any
from google.adk.agents import Agent
from google.adk.tools import ToolContext

from core.neo4j_client import tool_success, tool_error
from core.config import llm
from core.helper import get_neo4j_import_dir

# 从统一的工具箱中引入基础工具
from core.tools import get_approved_user_goal, sample_file

# ==========================================
# 1. 提示词定义 (Prompts)
# ==========================================
file_suggestion_agent_instruction = """
你是一个负责审查文件列表的建设性审查 AI。你的目标是推荐用于构建知识图谱的相关文件。

**任务：**
审查文件列表，评估它们与“已批准的用户目标”中所指定的图谱类型和描述是否相关。

对于任何你不确定的文件，请使用 'sample_file' 工具，以便更好地了解该文件的内容。
仅考虑结构化数据文件，如 CSV 或 JSON。

准备任务：
- 使用 'get_approved_user_goal' 工具获取已批准的用户目标

仔细思考，重复以下步骤直到完成：
1. 使用 'list_available_files' 工具列出可用文件
2. 评估每个文件的相关性，然后使用 'set_suggested_files' 工具记录推荐文件列表
3. 使用 'get_suggested_files' 工具获取推荐文件列表
4. 请求用户批准这组推荐文件
5. 如果用户有反馈意见，请牢记该反馈并返回步骤 1
6. 如果获得批准，使用 'approve_suggested_files' 工具记录该批准操作
"""

# ==========================================
# 2. 状态常量 & 专属工具函数 (Tools)
# ==========================================
ALL_AVAILABLE_FILES = "all_available_files"
SUGGESTED_FILES = "suggested_files"
APPROVED_FILES = "approved_files"


def list_available_files(tool_context: ToolContext) -> dict:
    """列出可用于构建知识图谱的文件。所有文件路径均相对于导入目录。"""
    import_dir = Path(get_neo4j_import_dir())

    # 查找导入目录下的所有文件，转为相对路径
    file_names = [
        str(x.relative_to(import_dir))
        for x in import_dir.rglob("*")
        if x.is_file()
    ]

    tool_context.state[ALL_AVAILABLE_FILES] = file_names
    return tool_success(ALL_AVAILABLE_FILES, file_names)


def set_suggested_files(suggest_files: List[str], tool_context: ToolContext) -> dict:
    """设置用于数据导入的建议文件列表。"""
    if not suggest_files:
        return tool_error("传入的文件列表为空！请先调用 list_available_files 工具查找系统中的有效文件。")

    tool_context.state[SUGGESTED_FILES] = suggest_files
    return tool_success(SUGGESTED_FILES, suggest_files)


def get_suggested_files(tool_context: ToolContext) -> Dict[str, Any]:
    """获取之前保存的建议文件列表。"""
    return tool_success(SUGGESTED_FILES, tool_context.state.get(SUGGESTED_FILES, []))


def approve_suggested_files(tool_context: ToolContext) -> Dict[str, Any]:
    """批准建议文件，使其作为已批准文件进行后续处理。"""
    if SUGGESTED_FILES not in tool_context.state:
        return tool_error("当前文件尚未设置。请勿执行操作...")

    # 转正升级
    tool_context.state[APPROVED_FILES] = tool_context.state[SUGGESTED_FILES]
    return tool_success(APPROVED_FILES, tool_context.state[APPROVED_FILES])


# 组装当前 Agent 需要的所有工具
file_suggestion_agent_tools = [
    get_approved_user_goal,
    list_available_files,
    sample_file,
    set_suggested_files,
    get_suggested_files,
    approve_suggested_files
]

# ==========================================
# 3. Agent 实例化
# ==========================================
file_suggestion_agent = Agent(
    name="file_suggestion_agent_v1",
    model=llm,
    description="帮助用户选择要导入的图谱源文件",
    instruction=file_suggestion_agent_instruction,
    tools=file_suggestion_agent_tools,
)