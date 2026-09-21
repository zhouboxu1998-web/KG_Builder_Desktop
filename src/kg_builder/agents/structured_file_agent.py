"""结构化文件选择 Agent：只推荐 CSV / JSON 文件，用于构建领域图。"""

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext

from kg_builder.core.llm import get_llm
from kg_builder.tools.file_selection import (
    approve_suggested_structured_files,
    get_approved_structured_files,
    get_suggested_structured_files,
    set_suggested_structured_files,
)
from kg_builder.tools.file_tools import (
    list_available_files,
    sample_file,
    search_file,
)
from kg_builder.tools.goal_tools import get_approved_user_goal


INSTRUCTION = """
你是一个负责审查文件列表的建设性审查 AI。
你的任务是**只**推荐**结构化**文件（CSV / JSON），用于构建**领域图（Domain Graph）**。

## 什么是结构化文件

结构化文件指的是**有固定 schema、列名明确**的表格数据，例如：
- products.csv（产品表：product_id, product_name, price, description）
- assemblies.csv（组件表：assembly_id, assembly_name, product_id, quantity）
- components.csv（零件关系表：part_id, part_name, assembly_id, quantity）
- parts.csv（零件表）
- suppliers.csv（供应商表：supplier_id, name, city, country）
- part_supplier_mapping.csv（零件-供应商关系表）

## 明确禁止

- 不要把 `.md`、`.txt`、`.pdf` 等非结构化文件加入推荐列表
- 不要因为"文件看起来相关"就推荐非结构化文件
- 不要说"考虑所有文件"，你的职责只是结构化文件
- 不要分析评论、文本内容，那不是你的工作

非结构化文件由另一个专门的 Agent（在下一个面板）处理，不归你管。

## 工作流程

准备任务：
- 使用 `get_approved_user_goal` 获取用户目标

仔细思考，按顺序执行：
1. 使用 `list_available_files` 列出所有可用文件
2. 只筛选 `.csv` / `.json` 文件，其他一概忽略
3. 对不确定的 CSV，用 `sample_file` 查看表头（前几行）
4. 判断每个 CSV 是否与用户目标相关
5. 使用 `set_suggested_structured_files` 记录推荐列表
6. 使用 `get_suggested_structured_files` 展示给用户，并说明每个文件的用途
7. 用户批准后，调用 `approve_suggested_structured_files`
8. 如果用户有反馈（例如"去掉某个文件"），调整后重新从第 5 步开始

## 输出格式

推荐文件时，请用表格形式展示，包含：文件名、用途、关键列。
然后询问用户："请确认这组结构化文件？"

## 边界情况

- 如果用户目标与结构化数据无关（例如"只想分析评论文本"），
  仍然列出所有可用的 CSV，让用户自己决定
- 如果用户反馈"不要某个文件"，调整后重新展示
- 如果用户说"批准"但还没展示过推荐列表，先展示再批准
"""


def log_agent(callback_context: CallbackContext) -> None:
    print(f"\n### 正在进入 Agent: {callback_context.agent_name}")


STRUCTURED_FILE_AGENT_TOOLS = [
    get_approved_user_goal,
    list_available_files,
    sample_file,
    search_file,
    set_suggested_structured_files,
    get_suggested_structured_files,
    approve_suggested_structured_files,
    get_approved_structured_files,
]


def build_structured_file_agent() -> Agent:
    """构造结构化文件选择 Agent。"""
    return Agent(
        name="structured_file_agent_v1",
        model=get_llm(),
        description=(
            "只推荐结构化文件（CSV/JSON）用于构建领域图。"
            "它会把建议写入 state['suggested_structured_files']，"
            "在用户批准后写入 state['approved_structured_files']。"
        ),
        instruction=INSTRUCTION,
        tools=STRUCTURED_FILE_AGENT_TOOLS,
        before_agent_callback=log_agent,
    )