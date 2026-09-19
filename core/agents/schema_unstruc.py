from google.adk.agents import Agent
from google.adk.tools import ToolContext

from core.neo4j_client import tool_success, tool_error
from core.config import llm
from core.tools import get_approved_user_goal, get_approved_files, sample_file

# ==========================================
# 1. 命名实体识别 (NER) 智能体
# ==========================================
ner_agent_instruction = """
你是一个顶级的算法程序，专用于分析文本文件。
目标：根据用户需求，建议可以从文本中提取哪些相关的“命名实体”（Named Entities）类型。

- 实体指人、地点、事物，不包括数量/数值。不要提出具体实例，而是提出类型（如 Person）。
- 优先复用“已知实体”（当前图谱中已存在的节点标签）。
- 发现新实体必须频繁出现且与目标高度相关。

准备：
- 使用 'get_approved_user_goal' 了解最终目标。
- 使用 'get_approved_files' 获取授权文件。
- 使用 'get_well_known_types' 获取当前图谱中已批准的节点标签。

步骤：
1. 'sample_file' 抽样阅读文件。
2. 思考已知实体和发现实体。
3. 使用 'set_proposed_entities' 保存实体类型建议。
4. 使用 'get_proposed_entities' 提取并展示给用户请求批准。
5. 若用户批准，使用 'approve_proposed_entities' 确认。
"""

PROPOSED_ENTITIES = "proposed_entity_types"
APPROVED_ENTITIES = "approved_entity_types"

def set_proposed_entities(proposed_entity_types: list[str], tool_context: ToolContext) -> dict:
    tool_context.state[PROPOSED_ENTITIES] = proposed_entity_types
    return tool_success(PROPOSED_ENTITIES, proposed_entity_types)

def get_proposed_entities(tool_context: ToolContext) -> dict:
    return tool_success(PROPOSED_ENTITIES, tool_context.state.get(PROPOSED_ENTITIES, []))

def approve_proposed_entities(tool_context: ToolContext) -> dict:
    if PROPOSED_ENTITIES not in tool_context.state:
        return tool_error("没有可批准的建议实体。请先设置建议，然后请求批准。")
    tool_context.state[APPROVED_ENTITIES] = tool_context.state.get(PROPOSED_ENTITIES)
    return tool_success(APPROVED_ENTITIES, tool_context.state[APPROVED_ENTITIES])

def get_well_known_types(tool_context: ToolContext) -> dict:
    """获取之前结构化Schema环节生成的已知节点标签"""
    plan = tool_context.state.get("proposed_construction_plan", {}) # 这里对接上一个流水线的产物
    approved_labels = list({entry["label"] for entry in plan.values() if entry["construction_type"] == "node"})
    return tool_success("approved_labels", approved_labels)

ner_schema_agent = Agent(
    name="ner_schema_agent_v1",
    description="提出可以从文本文件中提取的命名实体类型建议。",
    model=llm,
    instruction=ner_agent_instruction,
    tools=[
        get_approved_user_goal, get_approved_files, sample_file,
        get_well_known_types, set_proposed_entities, get_proposed_entities, approve_proposed_entities
    ]
)


# ==========================================
# 2. 事实提取 (Fact Type Extraction) 智能体
# ==========================================
fact_agent_instruction = """
你是一个专用于分析文本文件并提取“事实类型”的算法程序。
目标：建议可以从文本中提取的三元组事实类型 (主语, 谓语, 宾语)。

规则：
- 主语和宾语必须是【已批准的实体类型】。绝对不要发明新的实体类型。
- 建议的谓语应准确描述主客体之间的关系，并且实际存在于文本中。
- 使用 'add_proposed_fact' 保存建议。

步骤：
1. 获取用户目标和文件列表，并使用 'get_approved_entities' 获取可用实体白名单。
2. 抽样阅读文件。
3. 针对找出的每个事实类型调用 'add_proposed_fact'。
4. 使用 'get_proposed_facts' 提取展示。
5. 若用户批准，使用 'approve_proposed_facts' 确认。
"""

PROPOSED_FACTS = "proposed_fact_types"
APPROVED_FACTS = "approved_fact_types"

def get_approved_entities_tool(tool_context: ToolContext) -> dict:
    return tool_success(APPROVED_ENTITIES, tool_context.state.get(APPROVED_ENTITIES, []))

def add_proposed_fact(approved_subject_label: str, proposed_predicate_label: str, approved_object_label: str, tool_context: ToolContext) -> dict:
    approved_entities = tool_context.state.get(APPROVED_ENTITIES, [])
    if approved_subject_label not in approved_entities:
        return tool_error(f"找不到已批准的主语 {approved_subject_label}。请重试。")
    if approved_object_label not in approved_entities:
        return tool_error(f"找不到已批准的宾语 {approved_object_label}。请重试。")

    facts = tool_context.state.get(PROPOSED_FACTS, {})
    facts[proposed_predicate_label] = {
        "subject_label": approved_subject_label,
        "predicate_label": proposed_predicate_label,
        "object_label": approved_object_label
    }
    tool_context.state[PROPOSED_FACTS] = facts
    return tool_success(PROPOSED_FACTS, facts)

def get_proposed_facts(tool_context: ToolContext) -> dict:
    return tool_success(PROPOSED_FACTS, tool_context.state.get(PROPOSED_FACTS, {}))

def approve_proposed_facts(tool_context: ToolContext) -> dict:
    if PROPOSED_FACTS not in tool_context.state:
        return tool_error("没有可批准的事实草稿。请先添加建议事实。")
    tool_context.state[APPROVED_FACTS] = tool_context.state.get(PROPOSED_FACTS)
    return tool_success(APPROVED_FACTS, tool_context.state[APPROVED_FACTS])

relevant_fact_agent = Agent(
    name="fact_type_extraction_agent_v1",
    description="提出可以从文本中提取的相关事实类型的建议。",
    model=llm,
    instruction=fact_agent_instruction,
    tools=[
        get_approved_user_goal, get_approved_files, sample_file,
        get_approved_entities_tool, add_proposed_fact, get_proposed_facts, approve_proposed_facts
    ]
)