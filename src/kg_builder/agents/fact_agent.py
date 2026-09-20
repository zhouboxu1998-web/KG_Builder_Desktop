"""非结构化图谱 - 事实类型（Fact Type）提取 Agent。

职责：
    在 NER Agent 完成"实体类型批准"之后运行，
    分析同一批非结构化文本，提议可以提取的"事实类型"
    （即 (主语, 谓语, 宾语) 三元组中的关系）。

输出（关键）：
    通过工具 `add_proposed_fact` 写入 state['proposed_fact_types']；
    通过工具 `approve_proposed_facts` 在用户批准后写入
    state['approved_fact_types']。

配合关系：
    单独运行。其 initial_state 应**继承** NER Agent 结束时的 state，
    至少要包含：
        - approved_user_goal
        - approved_files
        - approved_entity_types  （核心：作为主谓宾的白名单）
"""

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext

from kg_builder.core.llm import get_llm
from kg_builder.tools.entity_tools import get_approved_entities
from kg_builder.tools.fact_tools import (
    add_proposed_fact,
    approve_proposed_facts,
    get_proposed_facts,
)
from kg_builder.tools.file_selection import get_approved_files, get_approved_unstructured_files
from kg_builder.tools.file_tools import sample_file
from kg_builder.tools.goal_tools import get_approved_user_goal


# ============================================================
# 一、指令（System Prompt）—— 分三段拼装
# ============================================================

# ---------- 1.1 角色与目标 ----------
fact_agent_role_and_goal = """
  你是一个顶级的算法程序，专用于分析文本文件。
  你的目标是：根据用户的具体需求，建议可以从文本中提取哪些相关的"事实类型"（type of facts）。
"""


# ---------- 1.2 设计提示（Hints）----------
fact_agent_hints = """
  不要建议具体个别的事实（实例），而是要提出与用户目标相关的通用的"事实类型"。
  例如，不要提出"ABK喜欢咖啡"这种具体事实，而是提出通用的事实类型："人 喜欢 饮料" (Person likes Beverage)。

  事实是由 (主语, 谓语, 宾语) —— 即 (subject, predicate, object) 组成的【三元组】。
  其中，主语（主体）和宾语（客体）必须是【已批准的实体类型】，而建议的谓语则提供它们之间如何关联的信息。
  例如，一个事实类型可以是 (Person, likes, Beverage)。

  事实的设计规则：
  - 只能使用【已批准的实体类型】作为主语或宾语。绝对不要去提出/发明新的实体类型。
  - 建议的谓语，应该准确描述已批准的主体和客体之间的关系。
  - 谓语应该针对"与用户目标高度相关的信息"进行优化（即：没用的关系不要提）。
  - 谓语必须实际出现在源文本中。不要凭空猜测（脑补/幻觉）。
  - 使用 'add_proposed_fact' 工具来记录（保存）每一个你建议的事实类型。
"""


# ---------- 1.3 思维链步骤（Chain-of-Thought）----------
fact_agent_chain_of_thought_directions = """
  任务准备阶段：
  - 使用 'get_approved_user_goal'（获取已批准的用户目标）工具，来明确用户的核心需求。
  - 使用 'get_approved_files'（获取已批准的文件）工具，来获取需要分析的文本列表。
  - 使用 'get_approved_entities'（获取已批准的实体）工具，获取可用的实体类型列表。

  一步一步地思考（Think step by step）：
  1. 使用 'get_approved_user_goal' 工具获取用户目标（时刻牢记任务导向）。
  2. 使用 'sample_file'（抽样文件）工具，对部分授权文件进行抽样阅读，以理解文本内容。
  3. 思考文本中的主语（subjects，主体）和宾语（objects，客体）是如何关联起来的。
  4. 针对你找出的【每一个】事实类型，分别调用 'add_proposed_fact'（添加建议事实）工具进行保存。
  5. 使用 'get_proposed_facts'（获取建议事实）工具，把你刚才添加的所有事实整合提取出来。
  6. 将这些建议的事实类型展示给用户，并附上你的解释说明（为什么建议这些事实）。
"""


# ---------- 1.4 三段拼装成最终 instruction ----------
fact_agent_instruction = f"""
{fact_agent_role_and_goal}
{fact_agent_hints}
{fact_agent_chain_of_thought_directions}
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
FACT_AGENT_TOOLS = [
    # —— 上下文获取 ——
    get_approved_user_goal,   # 用户目标
    get_approved_unstructured_files,       # 待处理文件列表
    get_approved_entities,    # 已批准实体（作为主宾白名单）

    # —— 文件探查 ——
    sample_file,              # 读取文件前 100 行

    # —— 事实提议流程 ——
    add_proposed_fact,        # 逐个添加建议事实
    get_proposed_facts,       # 读取建议事实（展示给用户）
    approve_proposed_facts,   # 用户批准后转正
]


def build_fact_agent() -> Agent:
    """构造事实类型（Fact Type）提取 Agent。

    Returns:
        一个配置完成的 Agent 实例，可用于：
        - 单独调试：make_agent_caller(build_fact_agent())
        - 作为 NER 阶段的后续阶段执行者
    """
    return Agent(
        name="fact_type_extraction_agent_v1",

        # 描述
        description=(
            "提出可以从文本文件中提取的相关事实类型（的建议）。"
            "它会把建议写入 state['proposed_fact_types']，"
            "在用户批准后写入 state['approved_fact_types']。"
        ),

        # 大脑
        model=get_llm(),

        # 员工手册
        instruction=fact_agent_instruction,

        # 工具箱
        tools=FACT_AGENT_TOOLS,

        # 生命周期回调
        before_agent_callback=log_agent,
    )