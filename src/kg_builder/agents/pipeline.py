"""
ADK 知识图谱构建器 - 顶层工作流编排（8 阶段版）。

阶段：

    1 UserIntent
    2 StructuredFiles
    3 SchemaLoop
    4 UnstructuredFiles
    5 NER
    6 Fact
    7 Build
    8 Query

Phase 2：

    在原有 Pipeline 业务逻辑上增加 PipelineRuntime。

重要：

    PipelineRuntime 只负责运行生命周期。

    PipelineSession 继续负责：

        AgentCaller
        session state
        stage state

    两者不混合。
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
from kg_builder.core.agent_runner import (
    AgentCaller,
    make_agent_caller,
)
from kg_builder.core.ingestion_engine import IngestionEngine
from kg_builder.core.pipeline_runtime import PipelineRuntime
from kg_builder.core.schema_engine import SchemaEngine

from kg_builder.state import (
    APPROVED_CONSTRUCTION_PLAN,
    APPROVED_USER_GOAL,
    FEEDBACK,
    PROPOSED_CONSTRUCTION_PLAN,
    SCHEMA_APPROVED_PLAN,
    SCHEMA_NORMALIZED_PLAN,
    SCHEMA_STATUS,
    SCHEMA_VALIDATION,
    SCHEMA_VALIDATION_FEEDBACK,
    INGESTION_STATUS,
    INGESTION_REPORT,
    INGESTION_ERRORS,
    INGESTION_WARNINGS,
    INGESTION_STATS,
)


# ============================================================
# 一、LoopAgent 的裁判节点
# ============================================================


class CheckStatusAndEscalate(BaseAgent):
    """
    LoopAgent 的第三个子节点：

    根据 state['feedback'] 决定是否终止循环。
    """

    async def _run_async_impl(
        self,
        ctx: InvocationContext,
    ) -> AsyncGenerator[Event, None]:

        feedback = (
            ctx.session.state.get(FEEDBACK)
            or ""
        ).strip()

        should_stop = (
            feedback.lower() == "valid"
        )

        if should_stop:
            print(
                "\n### [StopChecker] "
                "审查通过，终止循环。"
            )
        else:
            print(
                "\n### [StopChecker] "
                "审查未通过，进入下一轮迭代。"
            )

        yield Event(
            author=self.name,
            actions=EventActions(
                escalate=should_stop
            ),
        )


# ============================================================
# 二、Schema 提议/审查循环
# ============================================================


def build_schema_refinement_loop(
    max_iterations: int = 2,
) -> LoopAgent:
    """
    构建：

        提议
          ↓
        审查
          ↓
        裁判
          ↓
        Retry / Stop
    """

    return LoopAgent(
        name="schema_refinement_loop",
        description=(
            "分析已确认的结构化文件，并根据用户意图和反馈"
            "不断优化图谱模式，直到审查通过或达到最大迭代次数。"
        ),
        max_iterations=max_iterations,
        sub_agents=[
            build_schema_proposal_agent(),
            build_schema_critic_agent(),
            CheckStatusAndEscalate(
                name="StopChecker"
            ),
        ],
    )


# ============================================================
# 三、PipelineSession
# ============================================================


@dataclass
class PipelineSession:
    """
    Pipeline 的业务 Session。

    注意：

        这里仍然保存 AgentCaller。

        PipelineRuntime 不取代 PipelineSession。
    """

    intent_caller: Optional[AgentCaller] = None

    structured_files_caller: Optional[
        AgentCaller
    ] = None

    schema_caller: Optional[
        AgentCaller
    ] = None

    unstructured_files_caller: Optional[
        AgentCaller
    ] = None

    ner_caller: Optional[
        AgentCaller
    ] = None

    fact_caller: Optional[
        AgentCaller
    ] = None

    # 兼容旧字段
    files_caller: Optional[
        AgentCaller
    ] = None

    stage_states: Dict[
        str,
        Dict[str, Any],
    ] = field(
        default_factory=dict
    )

    def snapshot(
        self,
    ) -> Dict[str, Any]:

        return {
            key: dict(value)
            for key, value
            in self.stage_states.items()
        }

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
    """
    管理完整 8 阶段工作流。

    Phase 2 新增：

        self.runtime

    但不改变原有业务 Session。
    """

    def __init__(
        self,
        max_schema_iterations: int = 2,
        runtime: Optional[PipelineRuntime] = None,
    ):

        self.session = PipelineSession()

        self.max_schema_iterations = (
            max_schema_iterations
        )

        # Schema 批准状态
        self._approved_schema_plan: Optional[
            dict
        ] = None

        # ★ Phase 2
        #
        # 如果外部没有传 Runtime，
        # 则 Pipeline 自己创建一个。
        #
        # 这里不会创建新的 AgentRuntime，
        # PipelineRuntime 内部会复用 Phase 1 default_runtime。
        self.runtime = (
            runtime
            if runtime is not None
            else PipelineRuntime()
        )

        self.schema_engine = SchemaEngine()
        self.ingestion_engine = IngestionEngine()

    # ========================================================
    # 内部工具
    # ========================================================

    async def _inherit_state(
        self,
        prev_caller: Optional[AgentCaller],
        stage_name: str,
    ) -> Dict[str, Any]:

        if prev_caller is None:

            print(
                f"[Pipeline] 警告："
                f"{stage_name} 阶段未找到上游 caller，"
                f"将以空初始状态启动。"
            )

            return {}

        session = await prev_caller.get_session()

        return dict(
            session.state
        )

    async def _finish_stage_success(
        self,
        stage_name: str,
    ) -> None:
        """
        Stage 成功完成后的统一 Runtime 收尾。

        这里只负责 Runtime。

        不修改业务 state。
        """

        if self.runtime.status != "running":
            return

        if self.runtime.current_stage != stage_name:
            return

        self.runtime.finish_stage(
            stage_name=stage_name,
            status="success",
        )

    async def _finish_stage_error(
        self,
        stage_name: str,
        error: Exception,
    ) -> None:
        """
        Stage 失败后的统一 Runtime 收尾。
        """

        if self.runtime.status != "running":
            return

        if self.runtime.current_stage != stage_name:
            return

        self.runtime.fail_stage(
            stage_name=stage_name,
            error=str(error),
        )

    # ========================================================
    # Pipeline Run
    # ========================================================

    def start_run(
        self,
        metadata: Optional[
            Dict[str, Any]
        ] = None,
    ) -> str:
        """
        启动一次完整 Pipeline Run。

        注意：

            这里才创建 run_id。

            各 Stage 不应该自己创建 Run。
        """

        return self.runtime.start(
            metadata=metadata
        )

    def finish_run(
        self,
        status: str = "success",
        message: Optional[str] = None,
    ) -> None:
        """
        完成当前 Pipeline Run。
        """

        self.runtime.finish(
            status=status,
            message=message,
        )

    def get_run_id(
        self,
    ) -> Optional[str]:
        """
        获取当前 Pipeline Run ID。
        """

        return self.runtime.run_id

    def get_run_summary(
        self,
    ) -> Dict[str, Any]:
        """
        获取 Pipeline Runtime 摘要。
        """

        return self.runtime.get_summary()

    # ========================================================
    # 阶段 1：用户意图
    # ========================================================

    async def start_intent(
        self,
    ) -> AgentCaller:

        print(
            "[Pipeline] "
            "启动阶段 1：用户意图"
        )

        self.runtime.start_stage(
            "intent",
            agent_name="user_intent",
        )

        try:

            agent = build_user_intent_agent()

            self.session.intent_caller = (
                await make_agent_caller(
                    agent,
                    runtime=self.runtime.agent_runtime,
                    run_id=self.runtime.run_id,
                    stage="intent",
                )
            )

            return self.session.intent_caller

        except Exception as error:

            await self._finish_stage_error(
                "intent",
                error,
            )

            raise

    async def finalize_intent(
        self,
    ) -> None:

        if self.session.intent_caller is not None:

            s = await (
                self.session.intent_caller
                .get_session()
            )

            self.session.stage_states[
                "intent"
            ] = dict(s.state)

            await self._finish_stage_success(
                "intent"
            )

    # ========================================================
    # 阶段 2：结构化文件
    # ========================================================

    async def start_structured_selection(
        self,
    ) -> AgentCaller:

        print(
            "[Pipeline] "
            "启动阶段 2：结构化文件选择"
        )

        self.runtime.start_stage(
            "structured_files",
            agent_name="structured_file_agent",
        )

        try:

            state = await self._inherit_state(
                self.session.intent_caller,
                "结构化文件选择",
            )

            state.setdefault(
                APPROVED_USER_GOAL,
                {},
            )

            from kg_builder.agents.structured_file_agent import (
                build_structured_file_agent,
            )

            agent = (
                build_structured_file_agent()
            )

            self.session.structured_files_caller = (
                await make_agent_caller(
                    agent,
                    initial_state=state,
                    runtime=self.runtime.agent_runtime,
                    run_id=self.runtime.run_id,
                    stage="structured_files",
                )
            )

            return (
                self.session
                .structured_files_caller
            )

        except Exception as error:

            await self._finish_stage_error(
                "structured_files",
                error,
            )

            raise

    async def finalize_structured_selection(
        self,
    ) -> None:

        caller = (
            self.session
            .structured_files_caller
        )

        if caller is not None:

            s = await caller.get_session()

            self.session.stage_states[
                "structured_files"
            ] = dict(s.state)

            await self._finish_stage_success(
                "structured_files"
            )

    # ========================================================
    # 阶段 3：Schema
    # ========================================================

    async def start_schema_proposal(
        self,
    ) -> AgentCaller:

        print(
            "[Pipeline] "
            "启动阶段 3：Schema 提议/审查循环"
        )

        self.runtime.start_stage(
            "schema",
            agent_name="schema_refinement_loop",
        )

        try:

            state = await self._inherit_state(
                self.session
                .structured_files_caller,
                "Schema 提议",
            )

            state.setdefault(
                APPROVED_USER_GOAL,
                {},
            )

            state.setdefault(
                "approved_structured_files",
                [],
            )

            state.setdefault(
                PROPOSED_CONSTRUCTION_PLAN,
                {},
            )

            state.setdefault(
                FEEDBACK,
                "",
            )

            loop = (
                build_schema_refinement_loop(
                    max_iterations=(
                        self.max_schema_iterations
                    )
                )
            )

            self.session.schema_caller = (
                await make_agent_caller(
                    loop,
                    initial_state=state,
                    runtime=self.runtime.agent_runtime,
                    run_id=self.runtime.run_id,
                    stage="schema",
                )
            )

            return self.session.schema_caller

        except Exception as error:

            await self._finish_stage_error(
                "schema",
                error,
            )

            raise

    async def finalize_schema_proposal(
        self,
    ) -> None:

        if self.session.schema_caller is not None:

            s = await (
                self.session.schema_caller
                .get_session()
            )

            self.session.stage_states[
                "schema"
            ] = dict(s.state)

            await self._finish_stage_success(
                "schema"
            )

    # ========================================================
    # Schema 批准
    # ========================================================

    async def approve_schema_plan(self) -> dict:
        """
        批准当前提议的 Schema。

        Phase 3：

            Agent Session
                  ↓
            SchemaEngine
                  ↓
            Normalize
                  ↓
            Validate
                  ↓
            Approve
                  ↓
            Pipeline State

        注意：

            SchemaEngine 验证失败时，
            不允许批准。
        """

        caller = self.session.schema_caller

        if caller is None:
            return {
                "status": "error",
                "message": (
                    "Schema 阶段未启动，"
                    "请先在「③ 图谱结构」"
                    "面板请求方案"
                ),
            }

        session = await caller.get_session()

        state = session.state

        proposed = state.get(
            PROPOSED_CONSTRUCTION_PLAN
        )

        if not proposed:
            return {
                "status": "error",
                "message": (
                    "没有可批准的计划，"
                    "请先请求 Agent 提议方案"
                ),
            }

        try:

            # ====================================================
            # 1. 交给 SchemaEngine
            # ====================================================

            self.schema_engine.set_proposed_plan(
                proposed
            )

            # ====================================================
            # 2. Normalize
            # ====================================================

            normalized = (
                self.schema_engine
                .get_normalized_plan()
            )

            # ====================================================
            # 3. Validate
            # ====================================================

            validation = (
                self.schema_engine.validate()
            )

            # ====================================================
            # 4. 将 Engine 结果写回 Agent Session
            #
            # 这是兼容层。
            #
            # Agent Session 仍然可以读取这些信息，
            # 但它不再是 Schema 的唯一权威来源。
            # ====================================================

            state[
                SCHEMA_NORMALIZED_PLAN
            ] = normalized

            state[
                SCHEMA_VALIDATION
            ] = validation

            state[
                SCHEMA_VALIDATION_FEEDBACK
            ] = list(
                validation["errors"]
            )

            if not validation["valid"]:
                state[
                    SCHEMA_STATUS
                ] = "rejected"

                self.session.stage_states[
                    "schema"
                ] = dict(state)

                return {
                    "status": "error",
                    "message": (
                        "Schema Engine 验证失败。"
                    ),
                    "validation": validation,
                }

            # ====================================================
            # 5. 真正批准
            # ====================================================

            approved = (
                self.schema_engine.approve()
            )

            state[
                APPROVED_CONSTRUCTION_PLAN
            ] = approved

            state[
                SCHEMA_APPROVED_PLAN
            ] = approved

            state[
                SCHEMA_STATUS
            ] = "approved"

            # ====================================================
            # 6. 更新 Pipeline 的业务状态
            # ====================================================

            self.session.stage_states[
                "schema"
            ] = dict(state)

            return {
                "status": "success",
                "plan": approved,
                "count": len(approved),
                "validation": validation,
            }

        except Exception as error:

            return {
                "status": "error",
                "message": str(error),
            }

    def get_schema_state(self) -> Dict[str, Any]:
        """
        获取当前 Schema Engine 的完整状态。
        """

        return self.schema_engine.get_snapshot()

    def get_approved_schema(
            self,
    ) -> Optional[Dict[str, Any]]:
        """
        获取已经批准的 Schema。
        """

        return self.schema_engine.get_approved_plan()

    def is_schema_approved(
            self,
    ) -> bool:
        """
        判断 Schema 是否已经被 SchemaEngine 批准。
        """

        return self.schema_engine.is_approved()

    def reset_schema_approval(
            self,
    ) -> None:
        """
        重置 Schema Engine 的批准状态。
        """

        self.schema_engine.reset()

        self._approved_schema_plan = None

    def get_schema_plan(
            self,
    ) -> Optional[Dict[str, Any]]:
        """
        获取当前已经批准的 Schema。

        SchemaEngine 是唯一真实来源。
        """

        approved = (
            self.schema_engine.get_approved_plan()
        )

        if approved is not None:
            return approved

        # 兼容 Phase 2 旧状态
        return self._approved_schema_plan


    # ========================================================
    # 阶段 4：非结构化文件
    # ========================================================

    async def start_unstructured_selection(
        self,
    ) -> AgentCaller:

        print(
            "[Pipeline] "
            "启动阶段 4：非结构化文件选择"
        )

        self.runtime.start_stage(
            "unstructured_files",
            agent_name="unstructured_file_agent",
        )

        try:

            base = await self._inherit_state(
                self.session.intent_caller,
                "非结构化文件选择",
            )

            base.setdefault(
                APPROVED_USER_GOAL,
                {},
            )

            if self._approved_schema_plan:

                base[
                    APPROVED_CONSTRUCTION_PLAN
                ] = (
                    self._approved_schema_plan
                )

            elif "schema" in self.session.stage_states:

                base[
                    APPROVED_CONSTRUCTION_PLAN
                ] = self.session.stage_states[
                    "schema"
                ].get(
                    APPROVED_CONSTRUCTION_PLAN,
                    {},
                )

            from kg_builder.agents.unstructured_file_agent import (
                build_unstructured_file_agent,
            )

            agent = (
                build_unstructured_file_agent()
            )

            self.session.unstructured_files_caller = (
                await make_agent_caller(
                    agent,
                    initial_state=base,
                    runtime=self.runtime.agent_runtime,
                    run_id=self.runtime.run_id,
                    stage="unstructured_files",
                )
            )

            return (
                self.session
                .unstructured_files_caller
            )

        except Exception as error:

            await self._finish_stage_error(
                "unstructured_files",
                error,
            )

            raise

    async def finalize_unstructured_selection(
        self,
    ) -> None:

        caller = (
            self.session
            .unstructured_files_caller
        )

        if caller is not None:

            s = await caller.get_session()

            self.session.stage_states[
                "unstructured_files"
            ] = dict(s.state)

            await self._finish_stage_success(
                "unstructured_files"
            )

    # ========================================================
    # 阶段 5：NER
    # ========================================================

    async def start_ner(
        self,
    ) -> AgentCaller:

        print(
            "[Pipeline] "
            "启动阶段 5：NER"
        )

        self.runtime.start_stage(
            "ner",
            agent_name="ner_agent",
        )

        try:

            prev = (
                self.session
                .unstructured_files_caller
            )

            if prev is None:
                prev = (
                    self.session
                    .files_caller
                )

            base = await self._inherit_state(
                prev,
                "NER",
            )

            if self._approved_schema_plan:

                base[
                    APPROVED_CONSTRUCTION_PLAN
                ] = (
                    self._approved_schema_plan
                )

            elif "schema" in self.session.stage_states:

                base[
                    APPROVED_CONSTRUCTION_PLAN
                ] = self.session.stage_states[
                    "schema"
                ].get(
                    APPROVED_CONSTRUCTION_PLAN,
                    {},
                )

            base.setdefault(
                APPROVED_USER_GOAL,
                {},
            )

            base.setdefault(
                "approved_unstructured_files",
                [],
            )

            agent = build_ner_agent()

            self.session.ner_caller = (
                await make_agent_caller(
                    agent,
                    initial_state=base,
                    runtime=self.runtime.agent_runtime,
                    run_id=self.runtime.run_id,
                    stage="ner",
                )
            )

            return self.session.ner_caller

        except Exception as error:

            await self._finish_stage_error(
                "ner",
                error,
            )

            raise

    async def finalize_ner(
        self,
    ) -> None:

        if self.session.ner_caller is not None:

            s = await (
                self.session.ner_caller
                .get_session()
            )

            self.session.stage_states[
                "ner"
            ] = dict(s.state)

            await self._finish_stage_success(
                "ner"
            )

    # ========================================================
    # 阶段 6：Fact
    # ========================================================

    async def start_fact(
        self,
    ) -> AgentCaller:

        print(
            "[Pipeline] "
            "启动阶段 6：事实类型"
        )

        self.runtime.start_stage(
            "fact",
            agent_name="fact_agent",
        )

        try:

            state = await self._inherit_state(
                self.session.ner_caller,
                "事实类型",
            )

            state.setdefault(
                APPROVED_USER_GOAL,
                {},
            )

            state.setdefault(
                "approved_entity_types",
                [],
            )

            agent = build_fact_agent()

            self.session.fact_caller = (
                await make_agent_caller(
                    agent,
                    initial_state=state,
                    runtime=self.runtime.agent_runtime,
                    run_id=self.runtime.run_id,
                    stage="fact",
                )
            )

            return self.session.fact_caller

        except Exception as error:

            await self._finish_stage_error(
                "fact",
                error,
            )

            raise

    async def finalize_fact(
        self,
    ) -> None:

        if self.session.fact_caller is not None:

            s = await (
                self.session.fact_caller
                .get_session()
            )

            self.session.stage_states[
                "fact"
            ] = dict(s.state)

            await self._finish_stage_success(
                "fact"
            )

    async def start_build(self) -> dict:
        """启动知识图谱构建。

        Build 阶段只允许使用已经通过 SchemaEngine
        批准的 Schema。
        """

        print("[Pipeline] 启动阶段 7：知识图谱构建")

        if not self.schema_engine.is_approved():
            return {
                "status": "error",
                "message": (
                    "Schema 尚未批准，不能执行知识图谱构建。"
                ),
            }

        approved_plan = (
            self.schema_engine.get_approved_plan()
        )

        if not approved_plan:
            return {
                "status": "error",
                "message": (
                    "SchemaEngine 中没有可用的 approved schema。"
                ),
            }

        result = self.ingestion_engine.ingest(
            approved_plan
        )

        report = result.get(
            "report",
            self.ingestion_engine.get_report(),
        )

        ingestion_errors = (
                report.get("validation", {}).get(
                    "errors",
                    [],
                )
                + report.get(
            "graph_validation",
            {},
        ).get(
            "errors",
            [],
        )
        )

        ingestion_warnings = (
                report.get("validation", {}).get(
                    "warnings",
                    [],
                )
                + report.get(
            "graph_validation",
            {},
        ).get(
            "warnings",
            [],
        )
        )

        build_state = {
            INGESTION_STATUS: self.ingestion_engine.status,
            INGESTION_REPORT: report,
            INGESTION_ERRORS: ingestion_errors,
            INGESTION_WARNINGS: ingestion_warnings,
            INGESTION_STATS: report.get(
                "statistics",
                {},
            ),
        }

        caller = self.session.schema_caller

        if caller is not None:
            session = await caller.get_session()
            state = session.state

            state.update(build_state)

            self.session.stage_states[
                "build"
            ] = dict(state)
        else:
            self.session.stage_states[
                "build"
            ] = build_state

        return result

    async def build(self) -> dict:
        """执行阶段 7：知识图谱构建，并同步 PipelineRuntime。"""

        # ========================================================
        # 1. 启动 Build Runtime Stage
        # ========================================================

        self.start_build_stage()

        try:

            # ====================================================
            # 2. 执行原有 Build 业务逻辑
            #
            # build()
            #     ↓
            # start_build()
            #     ↓
            # SchemaEngine
            #     ↓
            # IngestionEngine
            # ====================================================

            result = await self.start_build()

            # ====================================================
            # 3. 根据 IngestionEngine 的最终结果
            #    更新 PipelineRuntime
            # ====================================================

            if result.get("status") == "success":

                self.finish_build_stage(
                    success=True
                )

            else:

                self.finish_build_stage(
                    success=False,
                    error=result.get(
                        "message",
                        "知识图谱构建失败。",
                    ),
                )

            return result

        except Exception as error:

            # ====================================================
            # 4. Build 发生未捕获异常
            # ====================================================

            self.finish_build_stage(
                success=False,
                error=str(error),
            )

            raise

    async def get_build_state(self) -> Dict[str, Any]:
        """获取最近一次 Build/Ingestion 状态。"""

        return dict(
            self.session.stage_states.get(
                "build",
                {},
            )
        )

    def get_ingestion_report(self) -> Dict[str, Any]:
        """获取最近一次图谱导入报告。"""

        return self.ingestion_engine.get_report()

    def reset_build(self) -> None:
        """重置 Build / Ingestion 状态。"""

        self.ingestion_engine.reset()

        self.session.stage_states.pop(
            "build",
            None,
        )

    # ========================================================
    # Stage 7 Build
    # ========================================================

    def start_build_stage(
        self,
    ) -> None:
        """
        Stage 7 Runtime Hook。

        注意：

            Phase 2 不改变 Build 业务逻辑。

            build_panel 以后真正执行 Build 时，
            只需要调用这个方法。
        """

        self.runtime.start_stage(
            "build",
            agent_name="kg_builder",
        )

    def finish_build_stage(
        self,
        success: bool = True,
        error: Optional[str] = None,
    ) -> None:
        """
        完成 Stage 7 Runtime Hook。
        """

        if success:

            self.runtime.finish_stage(
                "build",
                status="success",
            )

        else:

            self.runtime.fail_stage(
                "build",
                error=error,
            )

    # ========================================================
    # Stage 8 Query
    # ========================================================

    def start_query_stage(
        self,
    ) -> None:
        """
        Stage 8 Runtime Hook。

        Phase 2 只增加 Runtime 生命周期，
        不改变 Query 业务逻辑。
        """

        self.runtime.start_stage(
            "query",
            agent_name="kg_query",
        )

    def finish_query_stage(
        self,
        success: bool = True,
        error: Optional[str] = None,
    ) -> None:
        """
        完成 Stage 8 Runtime Hook。
        """

        if success:

            self.runtime.finish_stage(
                "query",
                status="success",
            )

        else:

            self.runtime.fail_stage(
                "query",
                error=error,
            )

    # ========================================================
    # 全流程测试
    # ========================================================

    async def run_full_pipeline(
        self,
        user_goal_prompt: str,
        structured_prompt: str = (
            "有哪些 CSV 文件可用？"
        ),
        schema_prompt: str = (
            "如何导入这些 CSV？"
        ),
        unstructured_prompt: str = (
            "有哪些 Markdown 文件可用？"
        ),
        ner_prompt: str = (
            "建议实体类型。"
        ),
        fact_prompt: str = (
            "建议事实类型。"
        ),
    ) -> Dict[str, Any]:

        # 如果调用者没有手动 start_run，
        # run_full_pipeline 自己创建一次 Pipeline Run。
        if self.runtime.status != "running":

            self.start_run(
                metadata={
                    "mode": "full_pipeline",
                }
            )

        try:

            # ------------------------------------------------
            # ①
            # ------------------------------------------------

            caller = await self.start_intent()

            await caller.chat(
                user_goal_prompt
            )

            await caller.chat(
                "批准那个目标。"
            )

            await self.finalize_intent()

            # ------------------------------------------------
            # ②
            # ------------------------------------------------

            caller = (
                await self.start_structured_selection()
            )

            await caller.chat(
                structured_prompt
            )

            await caller.chat(
                "批准这些结构化文件。"
            )

            await (
                self.finalize_structured_selection()
            )

            # ------------------------------------------------
            # ③
            # ------------------------------------------------

            caller = (
                await self.start_schema_proposal()
            )

            await caller.chat(
                schema_prompt
            )

            await (
                self.finalize_schema_proposal()
            )

            await self.approve_schema_plan()

            # ------------------------------------------------
            # ④
            # ------------------------------------------------

            caller = (
                await self.start_unstructured_selection()
            )

            await caller.chat(
                unstructured_prompt
            )

            await caller.chat(
                "批准这些非结构化文件。"
            )

            await (
                self.finalize_unstructured_selection()
            )

            # ------------------------------------------------
            # ⑤
            # ------------------------------------------------

            caller = await self.start_ner()

            await caller.chat(
                ner_prompt
            )

            await caller.chat(
                "批准这些建议的实体。"
            )

            await self.finalize_ner()

            # ------------------------------------------------
            # ⑥
            # ------------------------------------------------

            caller = await self.start_fact()

            await caller.chat(
                fact_prompt
            )

            await caller.chat(
                "批准这些建议的事实类型。"
            )

            await self.finalize_fact()

            # 当前 Phase 2：
            #
            # Build / Query 仍然由 UI 控制。
            #
            # 因此这里不自动执行 Stage 7 / 8。

            self.finish_run(
                status="success"
            )

            return self.session.snapshot()

        except Exception as error:

            if self.runtime.status == "running":

                self.finish_run(
                    status="error",
                    message=str(error),
                )

            raise

    # ========================================================
    # 状态查询
    # ========================================================

    async def get_current_state(
        self,
        stage: str,
    ) -> Dict[str, Any]:

        caller_map = {

            "intent":
                self.session.intent_caller,

            "structured_files":
                self.session.structured_files_caller,

            "schema":
                self.session.schema_caller,

            "unstructured_files":
                self.session.unstructured_files_caller,

            "ner":
                self.session.ner_caller,

            "fact":
                self.session.fact_caller,
        }

        caller = caller_map.get(
            stage
        )

        if caller is None:
            return {}

        session = await (
            caller.get_session()
        )

        return dict(
            session.state
        )

    # ========================================================
    # Reset
    # ========================================================

    def reset(self) -> None:
        self.session.reset()
        self._approved_schema_plan = None
        self.schema_engine.reset()
        self.ingestion_engine.reset()
        self.runtime.reset()


__all__ = [
    "CheckStatusAndEscalate",
    "build_schema_refinement_loop",
    "PipelineSession",
    "KGBuilderPipeline",
]