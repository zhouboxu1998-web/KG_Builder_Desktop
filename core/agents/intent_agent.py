from google.adk.agents import Agent
from google.adk.tools.tool_context import ToolContext
from core.neo4j_client import tool_success, tool_error
from core.config import llm

# ==========================================
# 1. 提示词定义 (Prompts)
# ==========================================
agent_role_and_goal = """
你是一名知识图谱用例方面的专家。
你的主要目标是帮助用户构思一个知识图谱用例。
"""

agent_conversational_hints = """
如果用户不确定该怎么做，请基于经典场景提供一些建议：
- 包含朋友、家人或职业关系的社交网络
- 包含供应商、客户和合作伙伴的物流网络
- 基于客户、产品和购买模式的推荐系统
- 针对具有可疑交易模式的多个账户的欺诈检测
- 包含电影、书籍或音乐的流行文化图谱
"""

agent_output_definition = """
一个用户目标包含两个组成部分：
- kind_of_graph：最多用 3 个词描述图谱，例如“社交网络”或“美国货运物流”
- description：用几句话描述该图谱的意图，例如“一个用于货物的动态路由和交付系统。”
"""

agent_chain_of_thought_directions = """
仔细思考并与用户协作：
1. 理解用户的目标，即一个包含描述的图谱类型 (kind_of_graph)。
2. 根据需要提出澄清问题。
3. 当你认为已经理解了他们的目标时，使用 'set_perceived_user_goal' 工具来记录你的理解。
4. 将你理解的用户目标展示给用户以供确认。
5. 如果用户同意，使用 'approve_perceived_user_goal' 工具来批准该用户目标。这会将该目标保存在状态 (state) 中的 'approved_user_goal' 键下。
"""

complete_agent_instruction = f"""
{agent_role_and_goal}
{agent_conversational_hints}
{agent_output_definition}
{agent_chain_of_thought_directions}
"""

# ==========================================
# 2. 状态常量 & 工具函数 (Tools)
# ==========================================
PERCEIVED_USER_GOAL = "perceived_user_goal"
APPROVED_USER_GOAL = "approved_user_goal"


def set_perceived_user_goal(kind_of_graph: str, graph_description: str, tool_context: ToolContext) -> dict:
    """
    设置感知的用户目标，包括图谱类型及其描述。

    Args:
        kind_of_graph: 对图谱类型的 2-3 个词的定义，例如“社交网络”
        graph_description: 对图谱的单段描述，总结其意图
    """
    user_goal_data = {"kind_of_graph": kind_of_graph, "description": graph_description}
    tool_context.state[PERCEIVED_USER_GOAL] = user_goal_data
    return tool_success(PERCEIVED_USER_GOAL, user_goal_data)


def approve_perceived_user_goal(tool_context: ToolContext) -> dict:
    """
    在获得用户批准后，将感知的用户目标记录为已批准的用户目标。
    只有在用户明确批准了感知的用户目标时，才调用此工具。
    """
    if PERCEIVED_USER_GOAL not in tool_context.state:
        return tool_error("perceived_user_goal 未设置。请先设置感知的用户目标，如果您不确定，请提出澄清问题。")

    tool_context.state[APPROVED_USER_GOAL] = tool_context.state[PERCEIVED_USER_GOAL]
    return tool_success(APPROVED_USER_GOAL, tool_context.state[APPROVED_USER_GOAL])


# ==========================================
# 3. Agent 实例化
# ==========================================
user_intent_agent = Agent(
    name="user_intent_agent_v1",
    model=llm,
    description="帮助用户构思知识图谱用例。",
    instruction=complete_agent_instruction,
    tools=[set_perceived_user_goal, approve_perceived_user_goal],
)