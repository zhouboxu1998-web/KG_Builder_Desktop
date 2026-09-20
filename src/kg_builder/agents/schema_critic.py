"""结构化图谱 - Schema 审查 Agent（Critic）。

职责：
    在 Schema 提议 Agent（schema_proposal_agent）之后运行，
    审查其写入 state['proposed_construction_plan'] 的构建计划是否：
        1. 与已批准的用户目标一致；
        2. 与已确认的文件内容一致；
        3. 内部逻辑自洽（唯一标识符、连通性、无冗余）。

输出（关键）：
    该 Agent 通过 `output_key=FEEDBACK`（即 "feedback"）把自己
    的最终回复**自动写入 session state 的 'feedback' 键**。
         - 若审查通过 → 写入 "valid"
         - 若审查不通过 → 写入 "retry" + 项目符号反馈列表

    随后，LoopAgent 的第三个子节点 CheckStatusAndEscalate 会读取
    state['feedback']，若为 "valid" 则触发 escalate 终止循环。

配合关系：
    该 Agent 是 schema_refinement_loop (LoopAgent) 的第二个子节点：
        schema_proposal_agent  →  schema_critic_agent  →  CheckStatusAndEscalate
"""

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext

from kg_builder.core.llm import get_llm
from kg_builder.state import FEEDBACK
from kg_builder.tools.file_selection import get_approved_files
from kg_builder.tools.file_tools import sample_file, search_file
from kg_builder.tools.goal_tools import get_approved_user_goal
from kg_builder.tools.schema_tools import get_proposed_construction_plan


# ============================================================
# 一、指令（System Prompt）—— 分三段拼装
# ============================================================

# ---------- 1.1 角色与目标 ----------
critic_agent_role_and_goal = """
    你是使用属性图（Property Graphs）进行知识图谱建模的专家。
    请审查（评估）提议的图谱模式（Schema），判断其与用户目标以及已确认文件的相关性和契合度。
"""


# ---------- 1.2 审查要点（Hints）----------
critic_agent_hints = """
    请从相关性和正确性的角度审查提议的图谱模式（Schema）：
    - 唯一标识符真的唯一吗？使用 'search_file' 工具进行验证。不接受复合标识符（Composite identifier，即由多列组合成的主键）。
    - 有没有任何"节点"实际上应该是"关系"？仔细检查唯一标识符是否真正唯一，确保它们不是指向其他节点的引用（外键）。使用 'search_file' 工具进行验证。
    - 你能手动在源数据中追踪线索，找到回答某个假设性业务问题所需的必要信息吗？（即：检验图谱逻辑是否走得通）
    - 图谱模式中的每个节点都连通了吗？可能遗漏了哪些关系？每个节点都应该至少连接到另外一个节点（不能出现孤立节点）。
    - 是否遗漏了层级关系或容器关系（hierarchical container relationships）？
    - 有没有任何关系是冗余的？如果两个节点之间的一条关系与它们之间的另一条关系在语义上是等同的，或者是前者的反向表达，那么这条关系就是冗余的。
"""


# ---------- 1.3 思维链步骤（Chain-of-Thought）----------
critic_agent_chain_of_thought_directions = """
    准备任务：
    - 使用 'get_approved_user_goal' 工具获取用户目标。
    - 使用 'get_approved_files' 工具获取已确认的文件列表。
    - 使用 'get_proposed_construction_plan' 工具获取当前的构建计划。
    - 使用 'sample_file'（抽样文件）和 'search_file'（搜索文件）工具来验证图谱模式设计。

    请仔细思考，使用工具执行操作，并在工具返回错误时重新评估你的操作逻辑：
    1. 分析提议构建计划中的每一条构建规则。
    2. 使用工具来验证这些构建规则的相关性和正确性。
    3. 如果图谱模式（Schema）看起来没问题，请仅用一个词回复：'valid'（有效）。
    4. 如果图谱模式存在问题，请回复 'retry'（重试），并以简洁的项目符号（列表）形式提供反馈意见（明确指出问题所在）。
"""


# ---------- 1.4 三段拼装成最终 instruction ----------
critic_agent_instruction = f"""
{critic_agent_role_and_goal}
{critic_agent_hints}
{critic_agent_chain_of_thought_directions}
"""


# ============================================================
# 二、回调函数 —— 进入 Agent 时打印日志
# ============================================================

def log_agent(callback_context: CallbackContext) -> None:
    """在 Agent 开始执行前打印一行日志，便于观察 LoopAgent 的迭代进度。"""
    print(f"\n### 正在进入 Agent: {callback_context.agent_name}")


# ============================================================
# 三、Agent 工厂函数
# ============================================================

# 该 Agent 能使用的工具列表（注意：只读工具，不包含任何 propose_* 工具）
SCHEMA_CRITIC_AGENT_TOOLS = [
    get_approved_user_goal,          # 读取用户目标
    get_approved_files,              # 读取已批准的文件列表
    get_proposed_construction_plan,  # 读取待审查的构建计划
    sample_file,                     # 抽取文件前 100 行（验证内容）
    search_file,                     # 类 grep 搜索（验证唯一性/字段）
]


def build_schema_critic_agent() -> LlmAgent:
    """构造 Schema 审查 Agent。

    Returns:
        一个配置完成的 LlmAgent 实例，可用于：
        - 单独调试：make_agent_caller(build_schema_critic_agent())
        - 放入 LoopAgent 的 sub_agents 列表（在 proposal 之后）
    """
    return LlmAgent(
        name="schema_critic_agent_v1",

        # 描述：向编排层说明其职责
        description=(
            "审查提议的图谱模式（Schema）与用户目标及已确认文件的相关性。"
            "如果通过则写入 state['feedback']='valid'，否则写入 'retry' + 反馈列表。"
        ),

        # 大脑
        model=get_llm(),

        # 员工手册
        instruction=critic_agent_instruction,

        # 工具箱（只读）
        tools=SCHEMA_CRITIC_AGENT_TOOLS,

        # ★★★ 关键配置 ★★★
        # output_key 会让该 Agent 的最终文本响应自动写入 session.state[FEEDBACK]
        # 后续的 CheckStatusAndEscalate 节点依赖这个键做决策
        output_key=FEEDBACK,

        # 生命周期回调
        before_agent_callback=log_agent,
    )