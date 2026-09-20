"""结构化图谱 - Schema 提议 Agent。

职责：
    根据已批准的用户目标和已确认的文件列表，提议一个图谱模式（Schema），
    通过指定构建规则，将文件转换为图谱的节点（Nodes）和关系（Relationships）。

设计要点：
    1. 使用 {feedback} 占位符 —— 若会话 state 中不存在 'feedback' 键，
       ADK 会抛 KeyError: Context variable not found: `feedback`。
       因此调用方在构造初始 state 时必须传入 'feedback'（哪怕是空字符串）。
    2. 该 Agent 属于 LoopAgent 的一个子步骤，其输出不会直接给用户看，
       而是被下一个 Critic Agent 审查；Critic 会把结果写入 state['feedback']，
       若为 'valid'，循环终止；否则该 Agent 会拿到反馈重新提议。
"""

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext

from kg_builder.core.llm import get_llm
from kg_builder.tools.file_selection import get_approved_files, get_approved_structured_files
from kg_builder.tools.file_tools import sample_file, search_file
from kg_builder.tools.goal_tools import get_approved_user_goal
from kg_builder.tools.schema_tools import (
    get_proposed_construction_plan,
    propose_node_construction,
    propose_relationship_construction,
    remove_node_construction,
    remove_relationship_construction,
)


# ============================================================
# 一、指令（System Prompt）—— 分三段拼装，方便维护
# ============================================================

# ---------- 1.1 角色与目标 ----------
proposal_agent_role_and_goal = """
    你是使用属性图（Property Graphs）进行知识图谱建模的专家。请提议
    一个图谱模式（Schema），通过指定构建规则，将已确认的文件转换
    为图谱实体（节点和关系）。最终生成的模式应当描述一个基于用户
    目标的知识图谱。

    如果有反馈信息，请在生成时将其纳入考虑：
    <feedback>
    {feedback}
    </feedback>
"""


# ---------- 1.2 设计提示（Hints）----------
proposal_agent_hints = """
    已确认文件列表中的每个文件最终都将成为一个节点（node）或一条关系（relationship）。
    判断一个文件大概率代表节点还是关系，主要基于文件名的提示（它是代表单一事物还是两种事物），
    以及在文件内发现的唯一标识符（unique identifiers）。

    因为唯一标识符对于决定图谱结构至关重要，
    请始终使用相关工具来验证疑似唯一标识符的唯一性。

    识别节点或关系的一般指导原则：
    - 如果文件名是单数，并且只有 1 个唯一标识符，它很可能是节点（node）。
    - 如果文件名是两件事物的组合，它很可能是一条完整关系（full relationship）。
    - 如果文件名听起来像节点，但内部存在多个唯一标识符，它可能包含了引用关系（即外键）。

    节点（Nodes）的设计规则：
    - 节点将拥有唯一标识符。
    - 节点 _可能_ 包含被用作引用关系的标识符（外键）。

    关系（Relationships）的设计规则：
    - 关系以两种方式出现：完整关系（full relationships）和引用关系（reference relationships）。

    完整关系（Full relationships）：
    - 完整关系出现在专门的关系文件中，通常带有组合名称（例如 part_supplier_mapping）。
    - 完整关系通常包含对源节点（source）和目标节点（destination）的引用。
    - 完整关系 _没有_ 唯一标识符，而是拥有外键的组合。
    - 缺乏单一的唯一标识符是判断该文件代表关系的一个强烈信号。

    引用关系（Reference relationships）：
    - 引用关系作为外键引用（foreign key references）出现在节点文件中。
    - 引用关系的外键列名通常会暗示目标节点（destination node）是什么。
    - 引用可能是层级/容器关系，通常带有类似父级（parent）等术语。
    - 引用可能是同级关系，这通常是指向同类节点类型的自引用（self-reference）。

    最终生成的图谱模式应当是一个连通图（connected graph），没有任何孤立的组件（节点）。
"""


# ---------- 1.3 思维链步骤（Chain-of-Thought）----------
proposal_agent_chain_of_thought_directions = """
    准备任务：
    - 使用 'get_approved_user_goal' 工具获取用户目标。
    - 使用 'get_approved_files' 工具获取已确认的文件列表。
    - 使用 'get_proposed_construction_plan' 工具获取当前的构建计划。

    请仔细思考，使用工具执行操作，并根据结果不断重新评估你的分析：
    1. 对于每个已确认的文件，考虑它代表一个节点还是关系。
    2. 对于每个标识符，通过使用 'search_file' 工具（在文件内搜索）来验证其唯一性。
    3. 使用前文提供的"节点与关系设计指导原则"，来决定该文件是代表节点还是关系。
    4. 对于节点文件，使用 'propose_node_construction' 工具提出节点构建方案。
    5. 如果节点中包含了引用关系（如外键），请使用 'propose_relationship_construction' 工具提出关系构建方案。
    6. 对于专门的关系文件，使用 'propose_relationship_construction' 工具提出关系构建方案。
    7. 如果你需要移除某个错误的构建，请使用 'remove_node_construction'（或类似移除）工具。
    8. 当你完成了所有的构建提议后，使用 'get_proposed_construction_plan' 工具获取最终提议计划并向用户展示。
"""


# ---------- 1.4 三段拼装成最终 instruction ----------
proposal_agent_instruction = f"""
{proposal_agent_role_and_goal}
{proposal_agent_hints}
{proposal_agent_chain_of_thought_directions}
"""


# ============================================================
# 二、回调函数 —— 进入 Agent 时打印日志
# ============================================================

def log_agent(callback_context: CallbackContext) -> None:
    """在 Agent 开始执行前打印一行日志，便于观察 LoopAgent 的迭代次数。"""
    print(f"\n### 正在进入 Agent: {callback_context.agent_name}")


# ============================================================
# 三、Agent 工厂函数
# ============================================================

# 该 Agent 能使用的工具列表
SCHEMA_PROPOSAL_AGENT_TOOLS = [
    # —— 上下文获取 ——
    get_approved_user_goal,          # 读取用户目标
    get_approved_structured_files,               # 读取已批准的文件列表
    get_proposed_construction_plan,  # 读取当前已提议的构建计划

    # —— 文件探查 ——
    sample_file,                     # 抽取文件前 100 行
    search_file,                     # 类 grep 搜索（验证唯一性）

    # —— 构建提议 ——
    propose_node_construction,        # 提议节点
    propose_relationship_construction,  # 提议关系

    # —— 构建撤销（自我纠错）——
    remove_node_construction,
    remove_relationship_construction,
]


def build_schema_proposal_agent() -> LlmAgent:
    """构造 Schema 提议 Agent。

    Returns:
        一个配置完成的 LlmAgent 实例，可用于：
        - 单独调试：make_agent_caller(build_schema_proposal_agent())
        - 放入 LoopAgent 的 sub_agents 列表
    """
    return LlmAgent(
        name="schema_proposal_agent_v1",

        # 描述：在多 Agent 系统中，其他 Agent（或上层编排）会读这段文字来判断何时调用它
        description=(
            "根据用户目标和已确认的文件列表，提议（设计）知识图谱模式（Schema）。"
            "它会把节点/关系的构建规则写入 state['proposed_construction_plan']。"
        ),

        # 大脑
        model=get_llm(),

        # 员工手册
        instruction=proposal_agent_instruction,

        # 工具箱
        tools=SCHEMA_PROPOSAL_AGENT_TOOLS,

        # 生命周期回调
        before_agent_callback=log_agent,
    )