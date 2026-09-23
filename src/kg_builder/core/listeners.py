"""
Agent Runtime 事件模型。

本模块不依赖 Google ADK 的具体 Event 类型，
而是定义 KG Builder 自己的统一运行时事件。

设计目标：
    1. Agent、Tool、Pipeline、UI 使用统一事件格式。
    2. 不让 UI 直接依赖 ADK Event 的内部结构。
    3. 后续可以很容易把事件写入文件、数据库或 OpenTelemetry。
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from kg_builder.core.errors import ConfigurationError


def generate_event_id() -> str:
    """生成唯一事件 ID。"""
    return uuid.uuid4().hex


def generate_run_id() -> str:
    """生成一次 Agent 执行的唯一 Run ID。"""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"{timestamp}-{suffix}"


@dataclass
class RuntimeEvent:
    """
    KG Builder 内部统一运行时事件。

    event_type 示例：

        run_started
        run_finished
        agent_started
        agent_finished
        adk_event
        agent_error

    status 示例：

        running
        success
        error
    """

    event_type: str
    run_id: str

    event_id: str = field(default_factory=generate_event_id)

    timestamp: str = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        ).isoformat()
    )

    stage: Optional[str] = None
    agent: Optional[str] = None

    status: Optional[str] = None

    duration_ms: Optional[float] = None

    message: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为普通 Python dict。"""
        return asdict(self)

    def to_json(self) -> str:
        """转换为 JSON 字符串。"""
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            default=str,
        )


class RuntimeEventStore:
    """
    线程安全的内存事件存储。

    当前阶段先使用内存存储。

    后续可以替换成：

        RuntimeEventStore
              ↓
        JSONLEventStore
              ↓
        SQLiteEventStore
              ↓
        PostgreSQL / OpenTelemetry

    而上层 Runtime 不需要修改。
    """

    def __init__(self, max_events: int = 10000):
        if max_events <= 0:
            raise ConfigurationError("max_events 必须大于 0")

        self.max_events = max_events

        self._events: List[RuntimeEvent] = []
        self._lock = threading.RLock()

    def append(self, event: RuntimeEvent) -> RuntimeEvent:
        """添加一个事件。"""
        with self._lock:
            self._events.append(event)

            # 防止长时间运行导致内存无限增长。
            if len(self._events) > self.max_events:
                overflow = len(self._events) - self.max_events
                del self._events[:overflow]

        return event

    def get_all(self) -> List[RuntimeEvent]:
        """获取全部事件快照。"""
        with self._lock:
            return list(self._events)

    def get_by_run(self, run_id: str) -> List[RuntimeEvent]:
        """获取指定 Run 的全部事件。"""
        with self._lock:
            return [
                event
                for event in self._events
                if event.run_id == run_id
            ]

    def clear(self) -> None:
        """清空事件。"""
        with self._lock:
            self._events.clear()

    def count(self) -> int:
        """返回当前事件数量。"""
        with self._lock:
            return len(self._events)


class RuntimeEventListener:
    """
    Runtime 事件监听器协议的轻量实现。

    可以通过继承这个类实现：

        - UI 实时显示
        - 日志输出
        - 文件持久化
        - Metrics
    """

    def on_event(self, event: RuntimeEvent) -> None:
        """收到一个运行时事件。"""
        return None


class CompositeEventListener(RuntimeEventListener):
    """将多个 Listener 组合起来。"""

    def __init__(
        self,
        listeners: Optional[List[RuntimeEventListener]] = None,
    ):
        self.listeners = listeners or []

    def add_listener(
        self,
        listener: RuntimeEventListener,
    ) -> None:
        """添加 Listener。"""
        self.listeners.append(listener)

    def on_event(self, event: RuntimeEvent) -> None:
        """向所有 Listener 广播事件。"""
        for listener in list(self.listeners):
            try:
                listener.on_event(event)
            except Exception:
                # Listener 不应该影响主业务流程。
                continue