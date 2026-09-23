"""
Query Runtime。

Phase 5-D 的职责：

    负责一次 Query 执行的运行时生命周期，连接：

        QueryEngine
            ↓
        QueryState
            ↓
        Query Runtime Metadata

它不负责：

    - Pipeline Stage 生命周期
    - Neo4j Driver 管理
    - ADK Tool
    - UI

PipelineRuntime 仍然负责 Stage 生命周期；
QueryRuntime 只关注“一次 Query 执行本身”。
"""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Dict, Optional

from kg_builder import config
from kg_builder.core.errors import QueryRuntimeError
from kg_builder.core.query_state import QueryState
from kg_builder.core.retry import RetryPolicy, TimeoutPolicy, run_sync_with_policy
from kg_builder.core.logger import logged_operation


class QueryRuntime:
    """管理一次 Query 执行的运行时信息。"""

    VALID_STATUSES = {
        "idle",
        "running",
        "success",
        "error",
    }

    def __init__(
        self,
        query_engine=None,
        query_state: Optional[QueryState] = None,
        retry_policy: Optional[RetryPolicy] = None,
        timeout_policy: Optional[TimeoutPolicy] = None,
    ):
        self.query_engine = query_engine
        self.query_state = (
            query_state
            if query_state is not None
            else QueryState()
        )

        self.status = "idle"
        self.run_id: Optional[str] = None
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.duration_ms: Optional[float] = None
        self.cypher: Optional[str] = None
        self.parameters: Dict[str, Any] = {}
        self.report: Dict[str, Any] = {}

        # Phase 1-C：Query 默认保守配置。
        self.retry_policy = retry_policy or RetryPolicy(
            max_attempts=config.KG_RETRY_MAX_ATTEMPTS,
            initial_delay=config.KG_RETRY_INITIAL_DELAY,
            max_delay=config.KG_RETRY_MAX_DELAY,
            multiplier=config.KG_RETRY_BACKOFF_MULTIPLIER,
            jitter=config.KG_RETRY_JITTER,
        )

        self.timeout_policy = timeout_policy or TimeoutPolicy(
            timeout_seconds=config.QUERY_TIMEOUT_SECONDS,
        )

    # ========================================================
    # Binding
    # ========================================================

    def bind(
        self,
        query_engine=None,
        query_state: Optional[QueryState] = None,
    ) -> None:
        """绑定 QueryEngine / QueryState 依赖。"""

        if query_engine is not None:
            self.query_engine = query_engine

        if query_state is not None:
            self.query_state = query_state

    # ========================================================
    # Lifecycle helpers
    # ========================================================

    @staticmethod
    def _now() -> str:
        """返回 UTC ISO 时间。"""

        return datetime.now(
            timezone.utc
        ).isoformat()

    def reset_state_only(self) -> None:
        """只重置 QueryState，不重置 QueryEngine。"""

        self.query_state.reset()

        self.status = "idle"
        self.run_id = None
        self.started_at = None
        self.finished_at = None
        self.duration_ms = None
        self.cypher = None
        self.parameters = {}
        self.report = {}

    # ========================================================
    # Execute
    # ========================================================

    @logged_operation("query_runtime.execute")
    def execute(
        self,
        cypher: str,
        parameters: Optional[dict] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        执行一次 Query 并记录运行时元数据。

        返回值仍然保持 QueryEngine 的标准结构，
        额外增加：

            runtime: {
                run_id,
                status,
                started_at,
                finished_at,
                duration_ms,
            }
        """

        if self.query_engine is None:
            raise QueryRuntimeError(
                "QueryRuntime 未绑定 QueryEngine。"
            )

        if self.query_state is None:
            raise QueryRuntimeError(
                "QueryRuntime 未绑定 QueryState。"
            )

        self.query_state.reset()

        self.status = "running"
        self.run_id = run_id
        self.started_at = self._now()
        self.finished_at = None
        self.duration_ms = None
        self.cypher = cypher
        self.parameters = (
            dict(parameters)
            if isinstance(parameters, dict)
            else {}
        )
        self.report = {}

        started_counter = perf_counter()

        try:
            result = run_sync_with_policy(
                self.query_engine.query,
                cypher=cypher,
                parameters=parameters,
                retry_policy=self.retry_policy,
                timeout_policy=self.timeout_policy,
                operation_name="query_engine.query",
            )

            if not isinstance(
                result,
                dict,
            ):
                result = {
                    "status": "error",
                    "query": cypher.strip()
                    if isinstance(cypher, str)
                    else None,
                    "parameters": dict(
                        parameters or {}
                    ),
                    "result_count": 0,
                    "result": [],
                    "error_message": (
                        "QueryEngine 返回了无效结果。"
                    ),
                }

            self.finished_at = self._now()
            self.duration_ms = (
                perf_counter() - started_counter
            ) * 1000

            self.status = result.get(
                "status",
                "error",
            )

            if self.status not in self.VALID_STATUSES:
                self.status = "error"
                result = dict(result)
                result["error_message"] = (
                    result.get(
                        "error_message"
                    )
                    or "QueryEngine 返回了无效状态。"
                )

            runtime_metadata = {
                "run_id": self.run_id,
                "status": self.status,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "duration_ms": self.duration_ms,
            }

            result = dict(result)
            result["runtime"] = runtime_metadata

            self.report = result

            self.query_state.update_from_report(
                result
            )

            return dict(result)

        except Exception as error:
            self.finished_at = self._now()
            self.duration_ms = (
                perf_counter() - started_counter
            ) * 1000
            self.status = "error"

            result = {
                "status": "error",
                "query": (
                    cypher.strip()
                    if isinstance(cypher, str)
                    else None
                ),
                "parameters": dict(
                    parameters or {}
                ),
                "result_count": 0,
                "result": [],
                "error_message": str(error),
                "error_code": getattr(
                    error,
                    "code",
                    None,
                ),
                "error_type": type(error).__name__,
                "error_details": dict(
                    getattr(
                        error,
                        "details",
                        {},
                    )
                    or {}
                ),
                "runtime": {
                    "run_id": self.run_id,
                    "status": "error",
                    "started_at": self.started_at,
                    "finished_at": self.finished_at,
                    "duration_ms": self.duration_ms,
                },
            }

            self.report = result

            self.query_state.update_from_report(
                result
            )

            return dict(result)

        except Exception as error:

            wrapped = QueryExecutionError.from_exception(
                error,
                message="Query Runtime 执行失败。",
            )

            self.finished_at = self._now()

            self.duration_ms = (
                perf_counter() - started_counter
            ) * 1000

            self.status = "error"

            result = {
                "status": "error",
                "query": (
                    cypher.strip()
                    if isinstance(cypher, str)
                    else None
                ),
                "parameters": dict(
                    parameters or {}
                ),
                "result_count": 0,
                "result": [],
                "error_message": str(wrapped),
                "error_code": wrapped.code,
                "error_type": wrapped.__class__.__name__,
                "runtime": {
                    "run_id": self.run_id,
                    "status": "error",
                    "started_at": self.started_at,
                    "finished_at": self.finished_at,
                    "duration_ms": self.duration_ms,
                },
            }

            self.report = result
            self.query_state.update_from_report(result)

            return dict(result)

    # ========================================================
    # Report
    # ========================================================

    def get_report(self) -> Dict[str, Any]:
        """获取最近一次 Query Runtime 报告。"""

        return dict(self.report)

    def snapshot(self) -> Dict[str, Any]:
        """获取当前 Query Runtime 快照。"""

        return {
            "status": self.status,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "cypher": self.cypher,
            "parameters": dict(
                self.parameters
            ),
            "report": dict(
                self.report
            ),
            "retry_policy": {
                "max_attempts": self.retry_policy.max_attempts,
                "initial_delay": self.retry_policy.initial_delay,
                "max_delay": self.retry_policy.max_delay,
                "multiplier": self.retry_policy.multiplier,
                "jitter": self.retry_policy.jitter,
            },
            "timeout_policy": {
                "timeout_seconds": self.timeout_policy.timeout_seconds,
                "enabled": self.timeout_policy.enabled,
            },
        }

    # ========================================================
    # Reset
    # ========================================================

    def reset(self) -> None:
        """完整重置 Query Runtime、QueryEngine 和 QueryState。"""

        if self.query_engine is not None:
            self.query_engine.reset()

        self.reset_state_only()


__all__ = [
    "QueryRuntime",
]
