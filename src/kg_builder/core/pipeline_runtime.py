"""
KG Builder Pipeline Runtime。

Phase 2：

    在 Phase 1 的 AgentRuntime 之上增加 Pipeline 层生命周期管理。

职责：

    PipelineRuntime
        ├── 管理一次完整 Pipeline 的 run_id
        ├── 管理 Pipeline 状态
        ├── 管理 Stage 生命周期
        ├── 记录 Stage 耗时
        ├── 记录 Stage 执行历史
        └── 生成 Pipeline summary

重要设计：

    本模块不重新实现 Agent Runtime。

    Phase 1 已经提供：

        AgentRuntime
        RuntimeEvent
        RuntimeEventStore

    Phase 2 直接复用这些能力。

状态定义：

    Pipeline：

        idle
        running
        success
        error

    Stage：

        pending
        running
        success
        error
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from kg_builder.core.events import RuntimeEvent
from kg_builder.core.runtime import AgentRuntime, default_runtime


# ============================================================
# StageRecord
# ============================================================


@dataclass
class StageRecord:
    """
    一个 Pipeline Stage 的运行记录。

    例如：

        intent
        structured_files
        schema
        unstructured_files
        ner
        fact
        build
        query
    """

    name: str

    display_name: str

    status: str = "pending"

    started_at: Optional[float] = None

    finished_at: Optional[float] = None

    duration_ms: Optional[float] = None

    agent_name: Optional[str] = None

    error: Optional[str] = None

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def start(
        self,
        agent_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        开始 Stage。
        """

        self.status = "running"

        self.started_at = time.perf_counter()

        self.finished_at = None

        self.duration_ms = None

        self.agent_name = agent_name

        self.error = None

        if metadata:
            self.metadata.update(metadata)

    def finish(
        self,
        status: str = "success",
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        完成 Stage。

        status：

            success
            error
        """

        self.finished_at = time.perf_counter()

        if self.started_at is not None:
            self.duration_ms = (
                self.finished_at - self.started_at
            ) * 1000

        self.status = status

        self.error = error

        if metadata:
            self.metadata.update(metadata)


# ============================================================
# PipelineRuntime
# ============================================================


class PipelineRuntime:
    """
    管理一次完整 KG Builder Pipeline 的生命周期。

    PipelineRuntime 不负责：

        - Agent 业务逻辑
        - Session state
        - Schema 业务逻辑
        - 文件选择
        - Neo4j 操作

    它只负责：

        Pipeline Run
        Stage 生命周期
        Runtime Event
        时间统计
    """

    DEFAULT_STAGES = [
        (
            "intent",
            "用户意图",
        ),
        (
            "structured_files",
            "结构化文件",
        ),
        (
            "schema",
            "图谱结构",
        ),
        (
            "unstructured_files",
            "非结构化文件",
        ),
        (
            "ner",
            "实体识别",
        ),
        (
            "fact",
            "事实类型",
        ),
        (
            "build",
            "构建",
        ),
        (
            "query",
            "查询",
        ),
    ]

    def __init__(
        self,
        agent_runtime: Optional[AgentRuntime] = None,
    ):
        """
        初始化 PipelineRuntime。

        注意：

            这里不会创建新的 AgentRuntime。

            默认直接复用 Phase 1 的 default_runtime。
        """

        self.agent_runtime = (
            agent_runtime
            if agent_runtime is not None
            else default_runtime
        )

        # Pipeline 初始状态。
        #
        # 注意：
        # 这是 Pipeline 状态，不是 Stage 状态。
        self.status = "idle"

        # 本次 Pipeline 对应的 Run ID。
        self.run_id: Optional[str] = None

        # Pipeline 开始时间。
        self.started_at: Optional[float] = None

        # Pipeline 结束时间。
        self.finished_at: Optional[float] = None

        # Pipeline 总耗时。
        self.duration_ms: Optional[float] = None

        # 当前运行的 Stage。
        self.current_stage: Optional[str] = None

        # 所有 Stage。
        self.stages: Dict[str, StageRecord] = {}

        # Stage 执行历史。
        self.stage_history: List[str] = []

        # Pipeline metadata。
        self.metadata: Dict[str, Any] = {}

        self._create_stages()

    # ========================================================
    # 初始化 Stage
    # ========================================================

    def _create_stages(self) -> None:
        """
        创建 Pipeline 默认 Stage。
        """

        self.stages = {
            name: StageRecord(
                name=name,
                display_name=display_name,
            )
            for name, display_name
            in self.DEFAULT_STAGES
        }

    # ========================================================
    # Pipeline Lifecycle
    # ========================================================

    def start(
        self,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        开始一次 Pipeline Run。

        返回：

            run_id
        """

        if self.status == "running":
            raise RuntimeError(
                "PipelineRuntime 已经正在运行。"
            )

        self.started_at = time.perf_counter()

        self.finished_at = None

        self.duration_ms = None

        self.status = "running"

        self.current_stage = None

        self.stage_history.clear()

        self.metadata = dict(
            metadata or {}
        )

        # 每次新的 Pipeline Run，
        # 都重新创建 StageRecord。
        self._create_stages()

        # ★ 复用 Phase 1 AgentRuntime。
        #
        # 不自己生成 run_id。
        #
        # 由 AgentRuntime.start_run() 生成。
        self.run_id = self.agent_runtime.start_run(
            agent_name="kg_builder_pipeline",
            stage="pipeline",
            metadata=self.metadata,
        )

        return self.run_id

    def finish(
        self,
        status: str = "success",
        message: Optional[str] = None,
    ) -> None:
        """
        完成 Pipeline。

        默认：

            success

        失败：

            error
        """

        if self.run_id is None:
            raise RuntimeError(
                "PipelineRuntime 尚未启动。"
            )

        self.finished_at = time.perf_counter()

        if self.started_at is not None:
            self.duration_ms = (
                self.finished_at - self.started_at
            ) * 1000

        # 如果 Pipeline 结束时还有 Stage 在运行，
        # 则先将这个 Stage 标记为 error。
        if self.current_stage is not None:

            record = self.stages.get(
                self.current_stage
            )

            if (
                record is not None
                and record.status == "running"
            ):
                record.finish(
                    status="error",
                    error=(
                        "Pipeline finished "
                        "while Stage was running."
                    ),
                )

                self._emit_stage_finished(
                    record
                )

        self.status = status

        # ★ 交给 Phase 1 AgentRuntime
        # 完成整个 Run。
        self.agent_runtime.finish_run(
            run_id=self.run_id,
            agent_name="kg_builder_pipeline",
            duration_ms=self.duration_ms or 0.0,
            stage="pipeline",
            status=status,
            message=(
                message
                or "Pipeline run finished"
            ),
        )

        self.current_stage = None

    # ========================================================
    # Stage Lifecycle
    # ========================================================

    def start_stage(
        self,
        stage_name: str,
        agent_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StageRecord:
        """
        开始一个 Stage。
        """

        self._ensure_running()

        if stage_name not in self.stages:
            raise ValueError(
                f"未知 Pipeline Stage：{stage_name}"
            )

        # 不允许两个 Stage 同时运行。
        if self.current_stage is not None:

            current = self.stages.get(
                self.current_stage
            )

            if (
                current is not None
                and current.status == "running"
            ):
                raise RuntimeError(
                    "已有 Stage 正在运行："
                    f"{self.current_stage}"
                )

        record = self.stages[stage_name]

        record.start(
            agent_name=agent_name,
            metadata=metadata,
        )

        self.current_stage = stage_name

        self.stage_history.append(
            stage_name
        )

        # ★ 使用 Phase 1 RuntimeEvent。
        #
        # 注意字段必须是：
        #
        #     agent
        #     metadata
        #
        # 而不是 agent_name / data。
        self.agent_runtime.emit(
            RuntimeEvent(
                event_type="pipeline_stage_started",
                run_id=self.run_id,
                stage=stage_name,
                agent=(
                    agent_name
                    or stage_name
                ),
                status="running",
                message=(
                    "Pipeline stage started: "
                    f"{stage_name}"
                ),
                metadata={
                    "stage_name": stage_name,
                    "display_name": (
                        record.display_name
                    ),
                    **(
                        metadata
                        or {}
                    ),
                },
            )
        )

        return record

    def finish_stage(
        self,
        stage_name: Optional[str] = None,
        status: str = "success",
        message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StageRecord:
        """
        完成一个 Stage。

        默认状态：

            success
        """

        self._ensure_running()

        if stage_name is None:
            stage_name = self.current_stage

        if stage_name is None:
            raise RuntimeError(
                "当前没有正在运行的 Stage。"
            )

        if stage_name not in self.stages:
            raise ValueError(
                f"未知 Pipeline Stage：{stage_name}"
            )

        record = self.stages[stage_name]

        record.finish(
            status=status,
            metadata=metadata,
        )

        self._emit_stage_finished(
            record,
            message=message,
        )

        if self.current_stage == stage_name:
            self.current_stage = None

        return record

    def fail_stage(
        self,
        stage_name: Optional[str] = None,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StageRecord:
        """
        将一个 Stage 标记为失败。
        """

        self._ensure_running()

        if stage_name is None:
            stage_name = self.current_stage

        if stage_name is None:
            raise RuntimeError(
                "当前没有正在运行的 Stage。"
            )

        if stage_name not in self.stages:
            raise ValueError(
                f"未知 Pipeline Stage：{stage_name}"
            )

        record = self.stages[stage_name]

        record.finish(
            status="error",
            error=error,
            metadata=metadata,
        )

        self._emit_stage_finished(
            record,
            message=(
                error
                or "Pipeline stage failed"
            ),
        )

        if self.current_stage == stage_name:
            self.current_stage = None

        return record

    # ========================================================
    # Runtime Event
    # ========================================================

    def _emit_stage_finished(
        self,
        record: StageRecord,
        message: Optional[str] = None,
    ) -> None:
        """
        发送 Stage 完成事件。
        """

        self.agent_runtime.emit(
            RuntimeEvent(
                event_type="pipeline_stage_finished",
                run_id=self.run_id,
                stage=record.name,
                agent=(
                    record.agent_name
                    or record.name
                ),
                status=record.status,
                duration_ms=record.duration_ms,
                message=(
                    message
                    or (
                        "Pipeline stage finished: "
                        f"{record.name}"
                    )
                ),
                metadata={
                    "stage_name": record.name,
                    "display_name": (
                        record.display_name
                    ),
                    "stage_status": (
                        record.status
                    ),
                    "error": record.error,
                    "metadata": dict(
                        record.metadata
                    ),
                },
            )
        )

    # ========================================================
    # 查询
    # ========================================================

    def get_stage(
        self,
        stage_name: str,
    ) -> StageRecord:
        """
        获取 StageRecord。
        """

        if stage_name not in self.stages:
            raise ValueError(
                f"未知 Pipeline Stage：{stage_name}"
            )

        return self.stages[stage_name]

    def get_events(self) -> List[RuntimeEvent]:
        """
        获取当前 Pipeline Run 的 RuntimeEvent。
        """

        if self.run_id is None:
            return []

        return self.agent_runtime.get_run_events(
            self.run_id
        )

    def get_total_duration_ms(self) -> float:
        """
        获取 Pipeline 总耗时。
        """

        if self.duration_ms is not None:
            return self.duration_ms

        if self.started_at is None:
            return 0.0

        return (
            time.perf_counter()
            - self.started_at
        ) * 1000

    def get_summary(self) -> Dict[str, Any]:
        """
        获取 Pipeline Runtime 摘要。
        """

        stages = {}

        for name, record in self.stages.items():

            stages[name] = {
                "name": record.name,
                "display_name": (
                    record.display_name
                ),
                "status": record.status,
                "started_at": (
                    record.started_at
                ),
                "finished_at": (
                    record.finished_at
                ),
                "duration_ms": (
                    record.duration_ms
                ),
                "agent_name": (
                    record.agent_name
                ),
                "error": record.error,
                "metadata": dict(
                    record.metadata
                ),
            }

        return {
            "run_id": self.run_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": (
                self.get_total_duration_ms()
            ),
            "current_stage": (
                self.current_stage
            ),
            "stage_history": list(
                self.stage_history
            ),
            "stages": stages,
            "metadata": dict(
                self.metadata
            ),
        }

    # ========================================================
    # Reset
    # ========================================================

    def reset(self) -> None:
        """
        重置 PipelineRuntime。

        Reset 后：

            status = idle
            run_id = None

        注意：

            不删除 Phase 1 RuntimeEventStore
            中已经产生的历史事件。
        """

        self.status = "idle"

        self.run_id = None

        self.started_at = None

        self.finished_at = None

        self.duration_ms = None

        self.current_stage = None

        self.stage_history.clear()

        self.metadata.clear()

        self._create_stages()

    # ========================================================
    # Internal
    # ========================================================

    def _ensure_running(self) -> None:
        """
        确保 Pipeline 正在运行。
        """

        if self.status != "running":
            raise RuntimeError(
                "PipelineRuntime 当前不是 running 状态："
                f"{self.status}"
            )

        if self.run_id is None:
            raise RuntimeError(
                "PipelineRuntime 正在运行，"
                "但 run_id 不存在。"
            )


__all__ = [
    "StageRecord",
    "PipelineRuntime",
]