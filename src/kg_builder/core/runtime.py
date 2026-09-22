"""
KG Builder Agent Runtime。

负责：

    - Run ID 管理
    - Agent 执行生命周期
    - Runtime Event 记录
    - 执行耗时统计
    - 异常记录
    - ADK Event 统一转换

注意：

    Runtime 不负责业务逻辑。

    Agent 仍然由 Google ADK 管理；
    Runtime 只是包裹执行过程。

这样可以避免 KG Builder 和 ADK 强耦合。
"""

from __future__ import annotations

import logging
import time
from typing import Any, AsyncGenerator, Dict, Optional

from google.adk.agents import Agent
from google.adk.events import Event

from kg_builder.core.events import (
    CompositeEventListener,
    RuntimeEvent,
    RuntimeEventListener,
    RuntimeEventStore,
    generate_run_id,
)


logger = logging.getLogger(__name__)


class AgentRuntime:
    """
    Agent 执行运行时。

    示例：

        runtime = AgentRuntime()

        run_id = runtime.start_run(
            agent_name="user_intent_agent"
        )

        runtime.agent_started(
            run_id=run_id,
            agent_name="user_intent_agent"
        )

        ...

        runtime.agent_finished(
            run_id=run_id,
            agent_name="user_intent_agent",
            duration_ms=1234
        )
    """

    def __init__(
        self,
        event_store: Optional[RuntimeEventStore] = None,
        listeners: Optional[list[RuntimeEventListener]] = None,
        max_events: int = 10000,
    ):
        self.event_store = event_store or RuntimeEventStore(
            max_events=max_events
        )

        self.listeners = CompositeEventListener(
            listeners or []
        )

    # ========================================================
    # Event
    # ========================================================

    def emit(
        self,
        event: RuntimeEvent,
    ) -> RuntimeEvent:
        """
        写入事件并通知 Listener。

        Listener 出错不会影响主流程。
        """
        self.event_store.append(event)

        try:
            self.listeners.on_event(event)
        except Exception:
            logger.exception(
                "Runtime Event Listener 执行失败"
            )

        return event

    def add_listener(
        self,
        listener: RuntimeEventListener,
    ) -> None:
        """添加事件监听器。"""
        self.listeners.add_listener(listener)

    # ========================================================
    # Run
    # ========================================================

    def start_run(
        self,
        agent_name: str,
        stage: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        创建一次新的 Agent Run。

        Returns:
            run_id
        """
        run_id = generate_run_id()

        self.emit(
            RuntimeEvent(
                event_type="run_started",
                run_id=run_id,
                stage=stage,
                agent=agent_name,
                status="running",
                message="Agent run started",
                metadata=metadata or {},
            )
        )

        return run_id

    def finish_run(
        self,
        run_id: str,
        agent_name: str,
        duration_ms: float,
        stage: Optional[str] = None,
        status: str = "success",
        message: Optional[str] = None,
    ) -> None:
        """记录一次 Run 完成。"""
        self.emit(
            RuntimeEvent(
                event_type="run_finished",
                run_id=run_id,
                stage=stage,
                agent=agent_name,
                status=status,
                duration_ms=duration_ms,
                message=message or "Agent run finished",
            )
        )

    # ========================================================
    # Agent lifecycle
    # ========================================================

    def agent_started(
        self,
        run_id: str,
        agent_name: str,
        stage: Optional[str] = None,
    ) -> None:
        """记录 Agent 开始执行。"""
        self.emit(
            RuntimeEvent(
                event_type="agent_started",
                run_id=run_id,
                stage=stage,
                agent=agent_name,
                status="running",
                message="Agent started",
            )
        )

    def agent_finished(
        self,
        run_id: str,
        agent_name: str,
        duration_ms: float,
        stage: Optional[str] = None,
    ) -> None:
        """记录 Agent 正常结束。"""
        self.emit(
            RuntimeEvent(
                event_type="agent_finished",
                run_id=run_id,
                stage=stage,
                agent=agent_name,
                status="success",
                duration_ms=duration_ms,
                message="Agent finished",
            )
        )

    def agent_error(
        self,
        run_id: str,
        agent_name: str,
        error: Exception,
        duration_ms: Optional[float] = None,
        stage: Optional[str] = None,
    ) -> None:
        """记录 Agent 执行异常。"""
        self.emit(
            RuntimeEvent(
                event_type="agent_error",
                run_id=run_id,
                stage=stage,
                agent=agent_name,
                status="error",
                duration_ms=duration_ms,
                message=str(error),
                metadata={
                    "exception_type": type(error).__name__,
                },
            )
        )

    # ========================================================
    # ADK Event
    # ========================================================

    def adk_event(
        self,
        run_id: str,
        event: Event,
        agent_name: Optional[str] = None,
        stage: Optional[str] = None,
    ) -> None:
        """
        将 Google ADK Event 转换成 KG Builder Runtime Event。

        不直接把整个 ADK Event 保存下来，
        避免把大量对象和敏感数据长期保存在内存中。
        """
        metadata: Dict[str, Any] = {
            "author": getattr(event, "author", None),
            "is_final": bool(
                event.is_final_response()
            )
            if hasattr(event, "is_final_response")
            else False,
            "partial": bool(
                getattr(event, "partial", False)
            ),
            "has_content": bool(
                getattr(event, "content", None)
            ),
            "has_actions": bool(
                getattr(event, "actions", None)
            ),
        }

        actions = getattr(event, "actions", None)

        if actions is not None:
            metadata["escalate"] = bool(
                getattr(actions, "escalate", False)
            )

        self.emit(
            RuntimeEvent(
                event_type="adk_event",
                run_id=run_id,
                stage=stage,
                agent=agent_name
                or getattr(event, "author", None),
                status="running",
                metadata=metadata,
            )
        )

    # ========================================================
    # 查询
    # ========================================================

    def get_run_events(
        self,
        run_id: str,
    ) -> list[RuntimeEvent]:
        """获取指定 Run 的所有事件。"""
        return self.event_store.get_by_run(run_id)

    def get_all_events(self) -> list[RuntimeEvent]:
        """获取全部事件。"""
        return self.event_store.get_all()


# ============================================================
# 全局 Runtime
# ============================================================

default_runtime = AgentRuntime()