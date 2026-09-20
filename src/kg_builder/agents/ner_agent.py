"""非结构化图谱 - 命名实体识别（NER）Agent。

职责：
    分析已批准的非结构化文本文件（Markdown / TXT 等），
    提议可以从文本中提取的"命名实体类型"，并交由用户批准。

输出（关键）：
    通过工具 `set_proposed_entities` 写入 state['proposed_entity_types']；
    通过工具 `approve_proposed_entities` 在用户批准后写入
    state['approved_entity_types']。

配合关系：
    单独运行（不属于 LoopAgent）。运行前，其 initial_state 中应包含：
        - approved_user_goal
        - approved_files
        - approved_construction_plan  （用于 get_well_known_types 复用已有节点标签）
"""

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext

from kg_builder.core.llm import get_llm
from kg_builder.tools.entity_tools import (
    approve_proposed_entities,
    get_approved_entities,
    get_proposed_entities,
    get_well_known_types,
    set_proposed_entities,
)
from kg_builder.tools.file_selection import get_approved_files, get_approved_unstructured_files
from kg_builder.tools.file_tools import sample_file
from kg_builder.tools.goal_tools import get_approved_user_goal


# ============================================================
# 一、指令（System Prompt）—— 分三段拼装
# ============================================================

# ---------- 1.1 角色与目标 ----------
ner_agent_role_and_goal = """
  你是一个顶级的算法程序，专用于分析文本文件。
  你的目标是：根据用户的具体需求，建议可以从文本中提取哪些相关的"命名实体"（Named Entities）。
"""


# ---------- 1.2 设计提示（Hints）----------
ner_agent_hints = """
  实体（Entities）指的是人、地点、事物和属性/性质，但不包括数量（quantities）。
  你的目标是提出一个实体【类型】（type）的列表，而不是提出实体的具体【实例】（instances）。

  在识别实体类型时，通常有两种主要方法：
  - 已知实体（well-known entities）：这些实体类型与现有图谱模式（graph schema）中已设定的"节点标签"紧密对应。
  - 发现实体（discovered entities）：这些实体类型可能还不存在于图谱模式中，但它们在源文本中频繁且稳定地出现。

  已知实体（well-known entities）的设计规则：
  - 始终使用现有的已知实体类型。例如，如果图谱中已经有一个已知类型叫 "Person"（人），而文本中也提到了人，那么请直接建议使用 "Person" 作为实体类型。
  - 优先复用（reusing）现有的实体类型，而不是去创建新的。

  发现实体（discovered entities）的设计规则：
  - 发现实体必须是在文本中被反复提及，并且与用户的最终目标高度相关的。
  - 始终去寻找那些能为现有图谱增加"深度"或"广度"的实体。
  - 例如，如果用户的目标是描绘社交网络，并且当前图谱已经有了 "Person"（人）节点，那么你应该通读文本，去发现像 "Hobby"（爱好）或 "Event"（事件）这样有价值的新实体类型。
  - 避免将数量/数值类型作为实体。数值类型最好作为现有实体或关系上的"属性（property）"来表示。
  - 例如，不要把 "Age"（年龄）建议为一个实体类型。年龄更适合作为 "Person" 实体上的一个附加属性 "age" 来表示。
"""


# ---------- 1.3 思维链步骤（Chain-of-Thought）----------
ner_agent_chain_of_thought_directions = """
  任务准备阶段：
  - 使用 'get_approved_user_goal'（获取用户目标）工具，来了解用户的最终目标是什么
  - 使用 'get_approved_files'（获取授权文件）工具，来获取你可以处理的文件列表
  - 使用 'get_well_known_types'（获取已知类型）工具，来获取当前图谱中已批准的节点标签（即现有分类）

  一步一步地思考（Think step by step）：
  1. 使用 'sample_file'（抽样文件）工具，对部分文件进行抽样阅读，以理解文本的内容。
  2. 思考文本中提到了哪些"已知实体"（well-known entities，即已存在于图谱中的类型）。
  3. 发掘文本中频繁出现、且有助于实现用户目标的"发现实体"（discovered entities，即需要新增的类型）。
  4. 使用 'set_proposed_entities'（设置建议实体）工具，将你找出的（已知的和新发现的）实体类型列表保存下来。
  5. 使用 'get_proposed_entities'（获取建议实体）工具，把你刚才保存的建议实体提取出来，并展示给用户看，请求用户批准（approval）。
  6. 如果用户批准了，使用 'approve_proposed_entities'（批准建议实体）工具，来最终确认这些实体类型。
  7. 如果用户不批准，请仔细考虑他们的反馈意见，并对你的建议列表进行迭代（重新修改并提交）。
"""


# ---------- 1.4 三段拼装成最终 instruction ----------
ner_agent_instruction = f"""
{ner_agent_role_and_goal}
{ner_agent_hints}
{ner_agent_chain_of_thought_directions}
"""


# ============================================================
# 二、回调函数 —— 进入 Agent 时打印日志
# ============================================================

def log_agent(callback_context: CallbackContext) -> None:
    """在 Agent 开始执行前打印一行日志。"""
    print(f"\n### 正在进入 Agent: {callback_context.agent_name}")


# ============================================================
# 三、Agent 工厂函数
# ============================================================

# 该 Agent 能使用的工具列表
NER_AGENT_TOOLS = [
    # —— 上下文获取 ——
    get_approved_user_goal,   # 用户目标
    get_approved_unstructured_files,       # 待处理文件列表
    get_well_known_types,     # 已批准的图谱节点标签（用于复用）

    # —— 文件探查 ——
    sample_file,              # 读取文件前 100 行

    # —— 实体提议流程 ——
    set_proposed_entities,    # 保存建议实体
    get_proposed_entities,    # 读取建议实体（展示给用户）
    approve_proposed_entities,  # 用户批准后转正
    get_approved_entities,    # 读取最终已批准实体（供下游使用）
]


def build_ner_agent() -> Agent:
    """构造 NER（命名实体识别）Agent。

    Returns:
        一个配置完成的 Agent 实例，可用于：
        - 单独调试：make_agent_caller(build_ner_agent())
        - 作为某一工作流阶段的执行者
    """
    return Agent(
        name="ner_schema_agent_v1",

        # 描述：向编排层/其他 Agent 说明其职责
        description=(
            "提出可以从文本文件中提取的命名实体类型（的建议）。"
            "它会把建议写入 state['proposed_entity_types']，"
            "在用户批准后写入 state['approved_entity_types']。"
        ),

        # 大脑
        model=get_llm(),

        # 员工手册
        instruction=ner_agent_instruction,

        # 工具箱
        tools=NER_AGENT_TOOLS,

        # 生命周期回调
        before_agent_callback=log_agent,
    )