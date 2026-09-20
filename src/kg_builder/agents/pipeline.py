"""ADK 知识图谱构建器 - 顶层工作流编排。

本模块负责把各个独立的 Agent 串联成一条完整的工作流，并管理各阶段之间
的**状态继承**（state handoff）。

工作流阶段：
    ① UserIntent     用户描述想要的图谱
    ② FileSelection  从 import 目录中筛选相关文件
    ③ SchemaLoop     提议 Schema → 审查 → (retry?) → 循环
    ④ NER            从非结构化文本中提议实体类型
    ⑤ Fact           基于已批准实体，提议事实类型（关系）
    ⑥ Build          （可选）根据 Schema 导入 CSV 到 Neo4j

设计要点：
    1. 各阶段通过 `initial_state` 从前一阶段继承 state。
       这样下游 Agent 就能直接读取上游的产物（例如 approved_files）。
    2. SchemaLoop 使用 ADK 的 LoopAgent，最多迭代 `max_iterations` 次。
       每轮的终止条件由 CheckStatusAndEscalate 读取 state['feedback'] 判断。
    3. 每个阶段的 Agent 都通过工厂函数（build_xxx）新建，
       保证状态隔离，避免跨阶段污染。
"""

from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, Optional

from google.adk.agents import LlmAgent, LoopAgent
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

from kg_builder.agents.fact_agent import build_fact_agent
from kg_builder.agents.file_suggestion import build_file_suggestion_agent
from kg_builder.agents.ner_agent import build_ner_agent
from kg_builder.agents.schema_critic import build_schema_critic_agent
from kg_builder.agents.schema_proposal import build_schema_proposal_agent
from kg_builder.agents.user_intent import build_user_intent_agent
from kg_builder.core.agent_runner import AgentCaller, make_agent_caller
from kg_builder.state import (
    APPROVED_CONSTRUCTION_PLAN,
    APPROVED_FILES,
    APPROVED_USER_GOAL,
    FEEDBACK,
    PROPOSED_CONSTRUCTION_PLAN,
)


# ============================================================
# 一、LoopAgent 的裁判节点：CheckStatusAndEscalate
# ============================================================

class CheckStatusAndEscalate(BaseAgent):
    """LoopAgent 的第三个子节点：根据 state['feedback'] 决定是否终止循环。

    行为：
        - 读取 state[FEEDBACK]
        - 若等于 "valid"（忽略大小写与首尾空白）→ 触发 escalate，终止 LoopAgent
        - 否则不做任何事，LoopAgent 自然进入下一轮

    为什么不用 LlmAgent？
        这个判断是纯逻辑，用 LLM 是浪费 token。BaseAgent 足够。
    """

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        feedback = (ctx.session.state.get(FEEDBACK) or "").strip()
        should_stop = feedback.lower() == "valid"

        if should_stop:
            print(f"\n### [StopChecker] 审查通过，终止循环。")
        else:
            print(f"\n### [StopChecker] 审查未通过，进入下一轮迭代。")

        yield Event(
            author=self.name,
            actions=EventActions(escalate=should_stop),
        )


# ============================================================
# 二、Schema 提议/审查循环的工厂
# ============================================================

def build_schema_refinement_loop(max_iterations: int = 2) -> LoopAgent:
    """构建"提议 → 审查 → 裁判"的迭代循环。

    Args:
        max_iterations: 最大迭代次数，每轮包含一次 proposal + 一次 critic。
                        建议 2~3 次：过小可能来不及修正，过大会浪费 token。

    Returns:
        一个配置完成的 LoopAgent 实例，可直接用于 `make_agent_caller`。
    """
    return LoopAgent(
        name="schema_refinement_loop",
        description=(
            "分析已确认的文件，并根据用户意图和反馈不断优化图谱模式，"
            "直到审查通过或达到最大迭代次数。"
        ),
        max_iterations=max_iterations,
        sub_agents=[
            build_schema_proposal_agent(),             # ① 提议
            build_schema_critic_agent(),               # ② 审查（写 state['feedback']）
            CheckStatusAndEscalate(name="StopChecker"),  # ③ 裁判（读 state['feedback']）
        ],
    )


# ============================================================
# 三、PipelineSession：记录各阶段的 AgentCaller
# ============================================================

@dataclass
class PipelineSession:
    """记录每个阶段的 AgentCaller 实例，便于后续阶段继承 state。

    每个 caller 自带一个独立的 InMemorySessionService，
    因此各阶段的状态是隔离的，跨阶段传递需显式拷贝 state。
    """

    intent_caller: Optional[AgentCaller] = None
    files_caller: Optional[AgentCaller] = None
    schema_caller: Optional[AgentCaller] = None
    ner_caller: Optional[AgentCaller] = None
    fact_caller: Optional[AgentCaller] = None

    # 记录各阶段的最终 state，方便外部（例如 UI）直接读取
    stage_states: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def snapshot(self) -> Dict[str, Any]:
        """返回各阶段状态的快照（浅拷贝），便于调试。"""
        return {k: dict(v) for k, v in self.stage_states.items()}

    def reset(self) -> None:
        """清空所有阶段的引用，重新开始。"""
        self.intent_caller = None
        self.files_caller = None
        self.schema_caller = None
        self.ner_caller = None
        self.fact_caller = None
        self.stage_states.clear()


# ============================================================
# 四、KGBuilderPipeline：顶层编排
# ============================================================

class KGBuilderPipeline:
    """管理完整工作流的编排队列。

    典型用法（在 UI 或脚本中）：

        pipeline = KGBuilderPipeline()

        # ① 用户意图
        caller = await pipeline.start_intent()
        await caller.chat("我想要一个供应链图谱……")
        await caller.chat("批准那个目标。")

        # ② 文件选择（自动继承 ① 的 state）
        caller = await pipeline.start_file_selection()
        await caller.chat("我们能用哪些文件？")
        await caller.chat("好的，就这么做！")

        # ③ Schema 循环（自动继承 ② 的 state）
        caller = await pipeline.start_schema_proposal()
        await caller.chat("如何导入这些文件？")

        # ④ NER（自动继承 ② 的 state）
        caller = await pipeline.start_ner()
        await caller.chat("把产品评论加到图谱中。")
        await caller.chat("批准这些实体。")

        # ⑤ 事实类型（自动继承 ④ 的 state）
        caller = await pipeline.start_fact()
        await caller.chat("建议事实类型。")
        await caller.chat("批准这些事实。")

        # 读取最终状态
        print(pipeline.session.snapshot())
    """

    def __init__(self, max_schema_iterations: int = 2):
        self.session = PipelineSession()
        self.max_schema_iterations = max_schema_iterations

    # --------------------------------------------------------
    # 内部工具：安全地读取上一阶段的 state
    # --------------------------------------------------------
    async def _inherit_state(
        self, prev_caller: Optional[AgentCaller], stage_name: str
    ) -> Dict[str, Any]:
        """读取上一阶段的 end state。

        若上一阶段未执行，返回空 dict（并打印警告）。
        """
        if prev_caller is None:
            print(f"[Pipeline] 警告：{stage_name} 阶段未找到上游 caller，"
                  f"将以空初始状态启动。")
            return {}
        session = await prev_caller.get_session()
        return dict(session.state)

    # --------------------------------------------------------
    # 阶段 ① 用户意图
    # --------------------------------------------------------
    async def start_intent(self) -> AgentCaller:
        """启动用户意图阶段。"""
        print("[Pipeline] 启动阶段 ①：用户意图")
        agent = build_user_intent_agent()
        self.session.intent_caller = await make_agent_caller(agent)
        return self.session.intent_caller

    async def finalize_intent(self) -> None:
        """把用户意图阶段的 end state 快照存下来。"""
        if self.session.intent_caller is not None:
            s = await self.session.intent_caller.get_session()
            self.session.stage_states["intent"] = dict(s.state)

    # --------------------------------------------------------
    # 阶段 ② 文件选择
    # --------------------------------------------------------
    async def start_file_selection(self) -> AgentCaller:
        """启动文件选择阶段，自动继承用户意图阶段的 state。"""
        print("[Pipeline] 启动阶段 ②：文件选择")

        state = await self._inherit_state(self.session.intent_caller, "文件选择")
        # 兜底：确保关键键存在
        state.setdefault(APPROVED_USER_GOAL, {})

        agent = build_file_suggestion_agent()
        self.session.files_caller = await make_agent_caller(
            agent, initial_state=state
        )
        return self.session.files_caller

    async def finalize_file_selection(self) -> None:
        if self.session.files_caller is not None:
            s = await self.session.files_caller.get_session()
            self.session.stage_states["files"] = dict(s.state)

    # --------------------------------------------------------
    # 阶段 ③ Schema 提议 / 审查循环
    # --------------------------------------------------------
    async def start_schema_proposal(self) -> AgentCaller:
        """启动 Schema 提议/审查循环，自动继承文件选择阶段 state。"""
        print("[Pipeline] 启动阶段 ③：Schema 提议/审查循环")

        state = await self._inherit_state(
            self.session.files_caller, "Schema 提议"
        )
        # 必要键兜底
        state.setdefault(APPROVED_FILES, [])
        state.setdefault(APPROVED_USER_GOAL, {})
        state.setdefault(PROPOSED_CONSTRUCTION_PLAN, {})
        # ★★★ 关键：feedback 必须存在，否则 schema_proposal 的 {feedback} 渲染会报错
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
    # 阶段 ④ NER（命名实体识别）
    # --------------------------------------------------------
    async def start_ner(self) -> AgentCaller:
        """启动 NER 阶段。

        注意：NER 面向的是**非结构化文件**（Markdown 等），
        其输入依赖 `approved_files` 与 `approved_construction_plan`。
        我们从文件选择阶段的 end state 继承，避免依赖 Schema 循环的中间状态。
        """
        print("[Pipeline] 启动阶段 ④：NER")

        # 优先继承文件选择阶段的 state（更干净）
        base = await self._inherit_state(
            self.session.files_caller, "NER"
        )
        # 若 Schema 阶段已批准了节点标签，也一并继承，让 get_well_known_types 有用
        if "schema" in self.session.stage_states:
            base[APPROVED_CONSTRUCTION_PLAN] = self.session.stage_states[
                "schema"
            ].get(APPROVED_CONSTRUCTION_PLAN, {})

        base.setdefault(APPROVED_USER_GOAL, {})
        base.setdefault(APPROVED_FILES, [])
        base.setdefault(APPROVED_CONSTRUCTION_PLAN, {})

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
    # 阶段 ⑤ 事实类型
    # --------------------------------------------------------
    async def start_fact(self) -> AgentCaller:
        """启动事实类型阶段，必须继承 NER 阶段的 end state（含已批准实体）。"""
        print("[Pipeline] 启动阶段 ⑤：事实类型")

        state = await self._inherit_state(self.session.ner_caller, "事实类型")
        state.setdefault(APPROVED_USER_GOAL, {})
        state.setdefault(APPROVED_FILES, [])
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
    # 便捷方法：运行完整流程（无交互版，仅用于自测/批处理）
    # --------------------------------------------------------
    async def run_full_pipeline(
        self,
        user_goal_prompt: str,
        file_selection_prompt: str = "我们能用哪些文件进行导入？",
        schema_prompt: str = "如何导入这些文件来构建知识图谱？",
        ner_prompt: str = "将产品评论添加到知识图谱中，以便追溯根本原因。",
        fact_prompt: str = "建议可以从文本中找到的事实类型。",
    ) -> Dict[str, Any]:
        """一次跑完整个工作流（不含人类打断），返回最终状态快照。

        说明：
            - 每一步末尾会自动发送"批准"指令，模拟用户确认。
            - 仅用于端到端自测或批处理场景，UI 中应逐步调用。
        """
        # ① 用户意图
        caller = await self.start_intent()
        await caller.chat(user_goal_prompt)
        await caller.chat("批准那个目标。")
        await self.finalize_intent()

        # ② 文件选择
        caller = await self.start_file_selection()
        await caller.chat(file_selection_prompt)
        await caller.chat("好的，就这么做！")
        await self.finalize_file_selection()

        # ③ Schema 循环
        caller = await self.start_schema_proposal()
        await caller.chat(schema_prompt)
        await self.finalize_schema_proposal()

        # ④ NER
        caller = await self.start_ner()
        await caller.chat(ner_prompt)
        await caller.chat("批准这些建议的实体。")
        await self.finalize_ner()

        # ⑤ 事实类型
        caller = await self.start_fact()
        await caller.chat(fact_prompt)
        await caller.chat("批准这些建议的事实类型。")
        await self.finalize_fact()

        return self.session.snapshot()

    # --------------------------------------------------------
    # 状态查询辅助
    # --------------------------------------------------------
    async def get_current_state(self, stage: str) -> Dict[str, Any]:
        """读取指定阶段的当前 state（不改变 pipeline 内部状态）。

        Args:
            stage: "intent" / "files" / "schema" / "ner" / "fact"

        Returns:
            该阶段 caller 的 session.state，未启动则返回空 dict。
        """
        caller_map = {
            "intent": self.session.intent_caller,
            "files": self.session.files_caller,
            "schema": self.session.schema_caller,
            "ner": self.session.ner_caller,
            "fact": self.session.fact_caller,
        }
        caller = caller_map.get(stage)
        if caller is None:
            return {}
        session = await caller.get_session()
        return dict(session.state)

    def reset(self) -> None:
        """重置整个 pipeline，清空所有 stage caller。"""
        self.session.reset()


# ============================================================
# 五、导出
# ============================================================

__all__ = [
    "CheckStatusAndEscalate",
    "build_schema_refinement_loop",
    "PipelineSession",
    "KGBuilderPipeline",
]