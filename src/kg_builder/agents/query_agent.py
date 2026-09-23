"""知识图谱 Query Agent 2.0。

职责：
    自然语言问题 → Entity/Schema Context → Query Planning → Cypher → Query Tool → Answer

当前版本仍使用单个 ADK Agent，以保持对现有 Pipeline 的兼容；
规划、实体链接与验证职责通过明确的 instruction + QueryPlanner/Query Tool 约束落实。
"""
from google.adk.agents import Agent

from kg_builder.core.llm import get_llm
from kg_builder.core.query_planner import QueryPlanner
from kg_builder.core.query_runtime import QueryRuntime
from kg_builder.tools.query_planner_tools import QUERY_PLANNER_TOOLS
from kg_builder.tools.query_tools import make_query_knowledge_graph_tool


QUERY_AGENT_INSTRUCTION = """
你是一名知识图谱 GraphRAG 查询专家。

目标：根据用户自然语言问题，从当前 Neo4j 知识图谱中检索真实事实并用中文回答。

工作流程必须遵守：

1. Entity Linking：先识别用户问题中的实体、对象、属性和约束；不要凭空假设实体名称。
2. Query Planning：确定需要的节点标签、关系类型、过滤条件和返回字段。
3. Schema Discovery：不确定图谱结构时，先使用只读 Cypher 检查 labels / relationship types。
4. Cypher Generation：生成参数化、最小必要范围的只读 Cypher。
5. Cypher Validation：只允许只读查询；不得执行 CREATE / MERGE / DELETE / SET / REMOVE / DROP / LOAD / CALL 等操作。
6. Graph Retrieval：调用 query_knowledge_graph 获取真实结果。
7. Answer：只根据真实结果回答；结果不足时明确说明，不要编造。

回答要求：
- 使用中文。
- 不输出内部推理过程。
- 不机械复述完整 Cypher。
- 结果为空时明确说明未找到数据。
"""


def build_query_agent(query_runtime: QueryRuntime) -> Agent:
    query_knowledge_graph = make_query_knowledge_graph_tool(query_runtime)
    return Agent(
        name="query_agent_v2",
        model=get_llm(),
        description="执行 Entity Linking、Query Planning、只读 Cypher 检索并生成中文答案。",
        instruction=QUERY_AGENT_INSTRUCTION,
        tools=[*QUERY_PLANNER_TOOLS, query_knowledge_graph],
    )


__all__ = ["QUERY_AGENT_INSTRUCTION", "build_query_agent", "QueryPlanner"]
