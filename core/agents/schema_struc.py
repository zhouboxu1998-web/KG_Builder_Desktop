from pathlib import Path
from typing import AsyncGenerator

from google.adk.tools import ToolContext
from google.adk.agents import LlmAgent, LoopAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.events import Event, EventActions

from core.neo4j_client import tool_success, tool_error
from core.config import llm
from core.helper import get_neo4j_import_dir

# 引入已封装的通用工具
from core.tools import get_approved_user_goal, get_approved_files, sample_file

# ==========================================
# 1. 架构师 (Proposer) 提示词
# ==========================================
proposal_agent_role_and_goal = """
    你是使用属性图（Property Graphs）进行知识图谱建模的专家。请提议一个图谱模式（Schema），
    通过指定构建规则，将已确认的文件转换为图谱实体（节点和关系）。
    最终生成的模式应当描述一个基于用户目标的知识图谱。

    如果有反馈信息，请在生成时将其纳入考虑：
    <feedback>
    {feedback}
    </feedback>
"""

proposal_agent_hints = """
    已确认文件列表中的每个文件最终都将成为一个节点（node）或一条关系（relationship）。
    判断一个文件大概率代表节点还是关系，主要基于文件名的提示，以及在文件内发现的唯一标识符。

    识别节点或关系的一般指导原则：
    - 如果文件名是单数，并且只有 1 个唯一标识符，它很可能是节点。
    - 如果文件名是两件事物的组合，它很可能是一条完整关系。
    - 如果文件名听起来像节点，但内部存在多个唯一标识符，它可能包含了引用关系。

    节点设计规则：节点将拥有唯一标识符。可能包含引用关系的标识符（外键）。
    关系设计规则：
    - 完整关系没有唯一标识符，而是拥有外键的组合。
    - 引用关系通常带有类似父级（parent）等术语。

    图谱必须是连通图，不能有孤立节点。
"""

proposal_agent_chain_of_thought_directions = """
    准备任务：
    - 使用 'get_approved_user_goal' 获取用户目标。
    - 使用 'get_approved_files' 获取文件列表。
    - 使用 'get_proposed_construction_plan' 获取当前的构建计划。

    1. 考虑每个文件代表节点还是关系。
    2. 对于每个标识符，使用 'search_file' 验证其唯一性。
    3. 决定该文件代表节点还是关系。
    4. 对于节点文件，使用 'propose_node_construction'。
    5. 如果包含引用关系，使用 'propose_relationship_construction'。
    6. 如果需要移除错误构建，使用 'remove_node_construction' 或类似工具。
    7. 完成后，使用 'get_proposed_construction_plan' 获取并展示计划。
"""

proposal_agent_instruction = f"""
{proposal_agent_role_and_goal}
{proposal_agent_hints}
{proposal_agent_chain_of_thought_directions}
"""

# ==========================================
# 2. 质检员 (Critic) 提示词
# ==========================================
critic_agent_instruction = """
    你是使用属性图进行知识图谱建模的专家。
    请审查提议的图谱模式（Schema），判断其与用户目标及已确认文件的契合度。

    请从相关性和正确性的角度审查：
    - 唯一标识符真的唯一吗？使用 'search_file' 工具验证。不接受复合标识符。
    - 有没有“节点”实际上应该是“关系”？仔细检查外键。
    - 图谱模式中的每个节点都连通了吗？是否遗漏了关系？
    - 有没有冗余关系？

    任务：
    1. 获取目标、文件列表和构建计划。使用抽样和搜索工具验证。
    2. 如果图谱模式没问题，请仅用一个词回复：'valid'
    3. 如果有问题，请回复 'retry'，并以列表形式提供明确的反馈意见。
"""

# ==========================================
# 3. 专属工具 (Tools)
# ==========================================
SEARCH_RESULTS = "search_results"
PROPOSED_CONSTRUCTION_PLAN = "proposed_construction_plan"
NODE_CONSTRUCTION = "node_construction"
RELATIONSHIP_CONSTRUCTION = "relationship_construction"

def search_file(file_path: str, query: str) -> dict:
    """在文本文件中搜索包含查询字符串的行。"""
    import_dir = Path(get_neo4j_import_dir())
    p = import_dir / file_path

    if not p.exists() or not p.is_file():
        return tool_error(f"文件不存在或无效: {file_path}")
    if not query:
        return tool_success(SEARCH_RESULTS, {"metadata": {"path": file_path, "query": query, "lines_found": 0}, "matching_lines": []})

    matching_lines = []
    search_query = query.lower()
    try:
        with open(p, 'r', encoding='utf-8') as file:
            for i, line in enumerate(file, 1):
                if search_query in line.lower():
                    matching_lines.append({"line_number": i, "content": line.strip()})
    except Exception as e:
        return tool_error(f"读取文件出错 {file_path}: {e}")

    return tool_success(SEARCH_RESULTS, {
        "metadata": {"path": file_path, "query": query, "lines_found": len(matching_lines)},
        "matching_lines": matching_lines
    })

def propose_node_construction(approved_file: str, proposed_label: str, unique_column_name: str, proposed_properties: list, tool_context: ToolContext) -> dict:
    """提议一个节点构建方案。"""
    search_results = search_file(approved_file, unique_column_name)
    if search_results.get("status") == "error": return search_results
    if search_results["search_results"]["metadata"]["lines_found"] == 0:
        return tool_error(f"{approved_file} 中没有列 {unique_column_name}")

    plan = tool_context.state.get(PROPOSED_CONSTRUCTION_PLAN, {})
    rule = {
        "construction_type": "node", "source_file": approved_file,
        "label": proposed_label, "unique_column_name": unique_column_name,
        "properties": proposed_properties
    }
    plan[proposed_label] = rule
    tool_context.state[PROPOSED_CONSTRUCTION_PLAN] = plan
    return tool_success(NODE_CONSTRUCTION, rule)

def propose_relationship_construction(
    approved_file: str, proposed_relationship_type: str,
    from_node_label: str, from_node_column: str, to_node_label: str, to_node_column: str,
    proposed_properties: list[str], tool_context: ToolContext
) -> dict:
    """提议一个关系构建方案。"""
    plan = tool_context.state.get(PROPOSED_CONSTRUCTION_PLAN, {})
    rule = {
        "construction_type": "relationship", "source_file": approved_file,
        "relationship_type": proposed_relationship_type, "from_node_label": from_node_label,
        "from_node_column": from_node_column, "to_node_label": to_node_label,
        "to_node_column": to_node_column, "properties": proposed_properties
    }
    plan[proposed_relationship_type] = rule
    tool_context.state[PROPOSED_CONSTRUCTION_PLAN] = plan
    return tool_success(RELATIONSHIP_CONSTRUCTION, rule)

def remove_node_construction(node_label: str, tool_context: ToolContext) -> dict:
    plan = tool_context.state.get(PROPOSED_CONSTRUCTION_PLAN, {})
    if node_label in plan:
        del plan[node_label]
        tool_context.state[PROPOSED_CONSTRUCTION_PLAN] = plan
        return tool_success("node_construction_removed", node_label)
    return tool_success("message", "未找到该节点的构建规则。无需移除。")

def remove_relationship_construction(relationship_type: str, tool_context: ToolContext) -> dict:
    plan = tool_context.state.get(PROPOSED_CONSTRUCTION_PLAN, {})
    if relationship_type in plan:
        plan.pop(relationship_type)
        tool_context.state[PROPOSED_CONSTRUCTION_PLAN] = plan
        return tool_success("relationship_construction_removed", relationship_type)
    return tool_success("message", "未找到该关系构建规则。无需移除。")

def get_proposed_construction_plan(tool_context: ToolContext) -> dict:
    return tool_context.state.get(PROPOSED_CONSTRUCTION_PLAN, {})

# ==========================================
# 4. Agent 定义与流水线组装 (LoopAgent)
# ==========================================
def log_agent(callback_context: CallbackContext) -> None:
    print(f"\n[流水线状态] 正在进入子 Agent: {callback_context.agent_name}")

schema_proposal_agent = LlmAgent(
    name="schema_proposal_agent_v1",
    description="根据用户目标和文件列表，提议知识图谱模式（Schema）",
    model=llm,
    instruction=proposal_agent_instruction,
    tools=[
        get_approved_user_goal, get_approved_files, get_proposed_construction_plan,
        sample_file, search_file, propose_node_construction, propose_relationship_construction,
        remove_node_construction, remove_relationship_construction
    ],
    before_agent_callback=log_agent
)

schema_critic_agent = LlmAgent(
    name="schema_critic_agent_v1",
    description="审查提议的图谱模式与用户目标及文件的相关性。",
    model=llm,
    instruction=critic_agent_instruction,
    tools=[get_approved_user_goal, get_approved_files, get_proposed_construction_plan, sample_file, search_file],
    output_key="feedback", # 审查结果自动存入 feedback 字段
    before_agent_callback=log_agent
)

class CheckStatusAndEscalate(BaseAgent):
    """裁判员：检查质检员的反馈是否为 valid"""
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        feedback = ctx.session.state.get("feedback", "valid").strip().lower()
        should_stop = ("valid" in feedback) # 如果包含 valid 则终止循环
        yield Event(author=self.name, actions=EventActions(escalate=should_stop))

# ★ 这是我们在外部要调用的总 Agent
schema_refinement_loop = LoopAgent(
    name="schema_refinement_loop",
    description="自动提议 Schema 并自我审查循环优化，直到通过审查",
    max_iterations=3, # 考虑到费用和时间，最大循环重试 3 次
    sub_agents=[
        schema_proposal_agent,
        schema_critic_agent,
        CheckStatusAndEscalate(name="StopChecker")
    ],
    before_agent_callback=log_agent
)