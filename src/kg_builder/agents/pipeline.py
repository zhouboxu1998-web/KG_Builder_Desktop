"""ADK 知识图谱构建器 - 顶层工作流编排（8 阶段版）。

阶段：
    ① UserIntent              用户描述想要的图谱
    ② StructuredFiles         选择结构化文件（CSV）
    ③ SchemaLoop              提议 Schema → 审查 → 循环 → 用户批准
    ④ UnstructuredFiles       选择非结构化文件（MD）
    ⑤ NER                     从非结构化文本提议实体类型
    ⑥ Fact                    基于实体，提议事实类型
    ⑦ Build                   （由 build_panel 控制）
    ⑧ Query                   （由 query_panel 控制）

关键设计：
    Schema 阶段跑完 LoopAgent 后，需要用户在 UI 里输入「批准」
    才会写入 pipeline._approved_schema_plan。
    build 阶段只在 schema 已批准时才执行。
"""

from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, Optional

from google.adk.agents import LoopAgent
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

from kg_builder.agents.fact_agent import build_fact_agent
from kg_builder.agents.ner_agent import build_ner_agent
from kg_builder.agents.schema_critic import build_schema_critic_agent
from kg_builder.agents.schema_proposal import build_schema_proposal_agent
from kg_builder.agents.user_intent import build_user_intent_agent
from kg_builder.core.agent_runner import AgentCaller, make_agent_caller
from kg_builder.state import (
    APPROVED_CONSTRUCTION_PLAN,
    APPROVED_USER_GOAL,
    FEEDBACK,
    PROPOSED_CONSTRUCTION_PLAN,
)


# ============================================================
# 一、LoopAgent 的裁判节点
# ============================================================

class CheckStatusAndEscalate(BaseAgent):
    """LoopAgent 的第三个子节点：根据 state['feedback'] 决定是否终止循环。"""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        feedback = (ctx.session.state.get(FEEDBACK) or "").strip()
        should_stop = feedback.lower() == "valid"

        if should_stop:
            print("\n### [StopChecker] 审查通过，终止循环。")
        else:
            print("\n### [StopChecker] 审查未通过，进入下一轮迭代。")

        yield Event(
            author=self.name,
            actions=EventActions(escalate=should_stop),
        )


# ============================================================
# 二、Schema 提议/审查循环的工厂
# ============================================================

def build_schema_refinement_loop(max_iterations: int = 2) -> LoopAgent:
    """构建"提议 → 审查 → 裁判"的迭代循环。"""
    return LoopAgent(
        name="schema_refinement_loop",
        description=(
            "分析已确认的结构化文件，并根据用户意图和反馈不断优化图谱模式，"
            "直到审查通过或达到最大迭代次数。"
        ),
        max_iterations=max_iterations,
        sub_agents=[
            build_schema_proposal_agent(),
            build_schema_critic_agent(),
            CheckStatusAndEscalate(name="StopChecker"),
        ],
    )


# ============================================================
# 三、PipelineSession
# ============================================================

@dataclass
class PipelineSession:
    """记录每个阶段的 AgentCaller，便于跨阶段继承 state。"""

    intent_caller: Optional[AgentCaller] = None
    structured_files_caller: Optional[AgentCaller] = None
    schema_caller: Optional[AgentCaller] = None
    unstructured_files_caller: Optional[AgentCaller] = None
    ner_caller: Optional[AgentCaller] = None
    fact_caller: Optional[AgentCaller] = None

    # 兼容旧字段
    files_caller: Optional[AgentCaller] = None

    stage_states: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def snapshot(self) -> Dict[str, Any]:
        return {k: dict(v) for k, v in self.stage_states.items()}

    def reset(self) -> None:
        self.intent_caller = None
        self.structured_files_caller = None
        self.schema_caller = None
        self.unstructured_files_caller = None
        self.ner_caller = None
        self.fact_caller = None
        self.files_caller = None
        self.stage_states.clear()


# ============================================================
# 四、KGBuilderPipeline
# ============================================================

class KGBuilderPipeline:
    """管理完整 8 阶段工作流的编排。"""

    def __init__(self, max_schema_iterations: int = 2):
        self.session = PipelineSession()
        self.max_schema_iterations = max_schema_iterations

        # ★ Schema 批准状态
        self._approved_schema_plan: Optional[dict] = None

    # --------------------------------------------------------
    # 内部工具
    # --------------------------------------------------------
    async def _inherit_state(
        self, prev_caller: Optional[AgentCaller], stage_name: str
    ) -> Dict[str, Any]:
        if prev_caller is None:
            print(
                f"[Pipeline] 警告：{stage_name} 阶段未找到上游 caller，"
                f"将以空初始状态启动。"
            )
            return {}
        session = await prev_caller.get_session()
        return dict(session.state)

    # --------------------------------------------------------
    # 阶段 ① 用户意图
    # --------------------------------------------------------
    async def start_intent(self) -> AgentCaller:
        print("[Pipeline] 启动阶段 ①：用户意图")
        agent = build_user_intent_agent()
        self.session.intent_caller = await make_agent_caller(agent)
        return self.session.intent_caller

    async def finalize_intent(self) -> None:
        if self.session.intent_caller is not None:
            s = await self.session.intent_caller.get_session()
            self.session.stage_states["intent"] = dict(s.state)

    # --------------------------------------------------------
    # 阶段 ② 结构化文件选择
    # --------------------------------------------------------
    async def start_structured_selection(self) -> AgentCaller:
        print("[Pipeline] 启动阶段 ②：结构化文件选择")

        state = await self._inherit_state(
            self.session.intent_caller, "结构化文件选择"
        )
        state.setdefault(APPROVED_USER_GOAL, {})

        from kg_builder.agents.structured_file_agent import (
            build_structured_file_agent,
        )
        agent = build_structured_file_agent()

        self.session.structured_files_caller = await make_agent_caller(
            agent, initial_state=state
        )
        return self.session.structured_files_caller

    async def finalize_structured_selection(self) -> None:
        caller = self.session.structured_files_caller
        if caller is not None:
            s = await caller.get_session()
            self.session.stage_states["structured_files"] = dict(s.state)

    # --------------------------------------------------------
    # 阶段 ③ Schema 提议 / 审查循环
    # --------------------------------------------------------
    async def start_schema_proposal(self) -> AgentCaller:
        print("[Pipeline] 启动阶段 ③：Schema 提议/审查循环")

        state = await self._inherit_state(
            self.session.structured_files_caller, "Schema 提议"
        )
        state.setdefault(APPROVED_USER_GOAL, {})
        state.setdefault("approved_structured_files", [])
        state.setdefault(PROPOSED_CONSTRUCTION_PLAN, {})
        state.setdefault(FEEDBACK, "")

        loop = build_schema_refinement_loop(
            max_iterations=self.max_schema_iterations
        )
        self.session.schema_caller = await make_agent_caller(
            loop, initial_state=state
        )
        return self.session.schema_caller

    async def finalize_schema_proposal(self) -> None:
        if self.session.schema_caller is not None:
            s = await self.session.schema_caller.get_session()
            self.session.stage_states["schema"] = dict(s.state)

    # --------------------------------------------------------
    # ★ Schema 批准
    # --------------------------------------------------------
    async def approve_schema_plan(self) -> dict:
        """批准当前提议的构建计划。

        Returns:
            {"status": "success", "plan": {...}, "count": N}
            或 {"status": "error", "message": "..."}
        """
        caller = self.session.schema_caller
        if caller is None:
            return {
                "status": "error",
                "message": "Schema 阶段未启动，请先在「③ 图谱结构」面板请求方案",
            }

        session = await caller.get_session()
        state = session.state

        proposed = state.get(PROPOSED_CONSTRUCTION_PLAN)
        if not proposed:
            return {
                "status": "error",
                "message": "没有可批准的计划，请先请求 Agent 提议方案",
            }

        # 尝试写入 session state（如果生效，下游也能读到）
        try:
            state[APPROVED_CONSTRUCTION_PLAN] = proposed
        except Exception:
            pass

        # 无论如何都记录在 pipeline 内部
        self._approved_schema_plan = dict(proposed)

        # 更新 stage_states
        self.session.stage_states["schema"] = dict(state)

        return {
            "status": "success",
            "plan": proposed,
            "count": len(proposed),
        }

    def get_schema_plan(self) -> Optional[dict]:
        """获取已批准的构建计划（如果已批准）。"""
        return self._approved_schema_plan

    def is_schema_approved(self) -> bool:
        """检查 Schema 是否已被批准。"""
        return self._approved_schema_plan is not None

    def reset_schema_approval(self) -> None:
        """清空 schema 批准状态（重新跑 Schema 时用）。"""
        self._approved_schema_plan = None

    # --------------------------------------------------------
    # 阶段 ④ 非结构化文件选择
    # --------------------------------------------------------
    async def start_unstructured_selection(self) -> AgentCaller:
        print("[Pipeline] 启动阶段 ④：非结构化文件选择")

        base = await self._inherit_state(
            self.session.intent_caller, "非结构化文件选择"
        )
        base.setdefault(APPROVED_USER_GOAL, {})

        # 合并 Schema 阶段的 approved_construction_plan
        if self._approved_schema_plan:
            base[APPROVED_CONSTRUCTION_PLAN] = self._approved_schema_plan
        elif "schema" in self.session.stage_states:
            base[APPROVED_CONSTRUCTION_PLAN] = self.session.stage_states[
                "schema"
            ].get(APPROVED_CONSTRUCTION_PLAN, {})

        from kg_builder.agents.unstructured_file_agent import (
            build_unstructured_file_agent,
        )
        agent = build_unstructured_file_agent()

        self.session.unstructured_files_caller = await make_agent_caller(
            agent, initial_state=base
        )
        return self.session.unstructured_files_caller

    async def finalize_unstructured_selection(self) -> None:
        caller = self.session.unstructured_files_caller
        if caller is not None:
            s = await caller.get_session()
            self.session.stage_states["unstructured_files"] = dict(s.state)

    # --------------------------------------------------------
    # 阶段 ⑤ NER
    # --------------------------------------------------------
    async def start_ner(self) -> AgentCaller:
        print("[Pipeline] 启动阶段 ⑤：NER")

        prev = self.session.unstructured_files_caller
        if prev is None:
            prev = self.session.files_caller  # 兼容

        base = await self._inherit_state(prev, "NER")

        # 合并 Schema 的 approved_construction_plan
        if self._approved_schema_plan:
            base[APPROVED_CONSTRUCTION_PLAN] = self._approved_schema_plan
        elif "schema" in self.session.stage_states:
            base[APPROVED_CONSTRUCTION_PLAN] = self.session.stage_states[
                "schema"
            ].get(APPROVED_CONSTRUCTION_PLAN, {})

        base.setdefault(APPROVED_USER_GOAL, {})
        base.setdefault("approved_unstructured_files", [])

        agent = build_ner_agent()
        self.session.ner_caller = await make_agent_caller(
            agent, initial_state=base
        )
        return self.session.ner_caller

    async def finalize_ner(self) -> None:
        if self.session.ner_caller is not None:
            s = await self.session.ner_caller.get_session()
            self.session.stage_states["ner"] = dict(s.state)

    # --------------------------------------------------------
    # 阶段 ⑥ 事实类型
    # --------------------------------------------------------
    async def start_fact(self) -> AgentCaller:
        print("[Pipeline] 启动阶段 ⑥：事实类型")

        state = await self._inherit_state(self.session.ner_caller, "事实类型")
        state.setdefault(APPROVED_USER_GOAL, {})
        state.setdefault("approved_entity_types", [])

        agent = build_fact_agent()
        self.session.fact_caller = await make_agent_caller(
            agent, initial_state=state
        )
        return self.session.fact_caller

    async def finalize_fact(self) -> None:
        if self.session.fact_caller is not None:
            s = await self.session.fact_caller.get_session()
            self.session.stage_states["fact"] = dict(s.state)

    # --------------------------------------------------------
    # 便捷方法：全流程（无交互，仅用于自测）
    # --------------------------------------------------------
    async def run_full_pipeline(
        self,
        user_goal_prompt: str,
        structured_prompt: str = "有哪些 CSV 文件可用？",
        schema_prompt: str = "如何导入这些 CSV？",
        unstructured_prompt: str = "有哪些 Markdown 文件可用？",
        ner_prompt: str = "建议实体类型。",
        fact_prompt: str = "建议事实类型。",
    ) -> Dict[str, Any]:
        # ①
        caller = await self.start_intent()
        await caller.chat(user_goal_prompt)
        await caller.chat("批准那个目标。")
        await self.finalize_intent()

        # ②
        caller = await self.start_structured_selection()
        await caller.chat(structured_prompt)
        await caller.chat("批准这些结构化文件。")
        await self.finalize_structured_selection()

        # ③
        caller = await self.start_schema_proposal()
        await caller.chat(schema_prompt)
        await self.finalize_schema_proposal()
        # ★ 自动批准
        await self.approve_schema_plan()

        # ④
        caller = await self.start_unstructured_selection()
        await caller.chat(unstructured_prompt)
        await caller.chat("批准这些非结构化文件。")
        await self.finalize_unstructured_selection()

        # ⑤
        caller = await self.start_ner()
        await caller.chat(ner_prompt)
        await caller.chat("批准这些建议的实体。")
        await self.finalize_ner()

        # ⑥
        caller = await self.start_fact()
        await caller.chat(fact_prompt)
        await caller.chat("批准这些建议的事实类型。")
        await self.finalize_fact()

        return self.session.snapshot()

    # --------------------------------------------------------
    # 状态查询
    # --------------------------------------------------------
    async def get_current_state(self, stage: str) -> Dict[str, Any]:
        caller_map = {
            "intent": self.session.intent_caller,
            "structured_files": self.session.structured_files_caller,
            "schema": self.session.schema_caller,
            "unstructured_files": self.session.unstructured_files_caller,
            "ner": self.session.ner_caller,
            "fact": self.session.fact_caller,
        }
        caller = caller_map.get(stage)
        if caller is None:
            return {}
        session = await caller.get_session()
        return dict(session.state)

    def reset(self) -> None:
        self.session.reset()
        self._approved_schema_plan = None


__all__ = [
    "CheckStatusAndEscalate",
    "build_schema_refinement_loop",
    "PipelineSession",
    "KGBuilderPipeline",
]