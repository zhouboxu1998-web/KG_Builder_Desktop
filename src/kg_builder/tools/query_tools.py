"""
ADK Query Tool。

Phase 5-E 的职责：

    将已经完成的 QueryRuntime 暴露为 Google ADK Function Tool。

调用链：

    ADK Agent
        ↓
    query_knowledge_graph()
        ↓
    QueryRuntime
        ↓
    QueryEngine
        ↓
    Neo4jClient
        ↓
    Neo4j

重要设计：

1. Query Tool 只负责 Agent Tool 边界。
2. Query 执行仍然交给 QueryRuntime。
3. QueryState 仍然由 QueryRuntime 更新。
4. Tool Context State 会同步 Query 状态，方便 ADK Agent 后续读取。
5. Agent-facing Query Tool 采用保守的只读 Cypher 策略。
6. QueryPanel 仍然可以使用原来的开发者模式，不受本策略影响。
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from time import perf_counter
from typing import Any, Callable, Dict, Optional

from google.adk.tools import ToolContext

from kg_builder.core.errors import ToolExecutionError, ToolInputError
from kg_builder.core.query_runtime import QueryRuntime
from kg_builder.state import (
    QUERY_CYPHER,
    QUERY_ERROR,
    QUERY_PARAMETERS,
    QUERY_REPORT,
    QUERY_RESULT,
    QUERY_RESULT_COUNT,
    QUERY_STATUS,
)


# ============================================================
# Agent Query Safety Policy
# ============================================================

READ_ONLY_START_KEYWORDS = {
    "MATCH",
    "OPTIONAL",
    "WITH",
    "UNWIND",
    "RETURN",
    "SHOW",
    "PROFILE",
    "EXPLAIN",
}

WRITE_KEYWORDS = {
    "CREATE",
    "MERGE",
    "DELETE",
    "DETACH",
    "SET",
    "REMOVE",
    "DROP",
    "LOAD",
    "FOREACH",
    "ALTER",
    "GRANT",
    "DENY",
    "REVOKE",
    "TERMINATE",
    "START",
    "STOP",
}


# ============================================================
# Internal helpers
# ============================================================


def _strip_cypher_literals(text: str) -> str:
    """
    移除字符串字面量与反引号标识符中的内容。

    这样可以避免下面这种合法查询因为字符串内容包含 CREATE
    而被误判：

        MATCH (n)
        WHERE n.description CONTAINS 'CREATE'
        RETURN n

    这里不是完整的 Cypher parser，而是一个保守的 Tool 层防护。
    """

    output = []

    quote: Optional[str] = None

    i = 0

    while i < len(text):
        char = text[i]

        if quote is None:
            if char in ("'", '"', "`"):
                quote = char
                output.append(" ")
            else:
                output.append(char)

            i += 1
            continue

        if char == "\\" and quote in ("'", '"'):
            output.append(" ")

            if i + 1 < len(text):
                output.append(" ")
                i += 2
            else:
                i += 1

            continue

        if char == quote:
            # Cypher 字符串支持两个连续的引号表示一个引号。
            if (
                quote in ("'", '"')
                and i + 1 < len(text)
                and text[i + 1] == quote
            ):
                output.append(" ")
                output.append(" ")
                i += 2
                continue

            quote = None
            output.append(" ")
            i += 1
            continue

        output.append(" ")
        i += 1

    return "".join(output)


def _normalize_parameters(
    parameters: Optional[dict],
) -> Dict[str, Any]:
    """标准化 Tool 参数。"""

    if parameters is None:
        return {}

    if not isinstance(parameters, dict):
        raise ToolInputError(
            "parameters 必须是 dict 或 None。"
        )

    return dict(parameters)


def _utc_now() -> str:
    """返回 UTC ISO 时间。"""

    return datetime.now(
        timezone.utc
    ).isoformat()


def _sync_tool_context_state(
    tool_context: ToolContext,
    result: Dict[str, Any],
) -> None:
    """
    将 Query 结果同步到 ADK ToolContext State。

    ADK 当前的 Context / ToolContext 允许通过
    ctx.state['key'] = value 直接修改当前 Session State。
    """

    state = tool_context.state

    state[QUERY_STATUS] = result.get(
        "status",
        "error",
    )

    state[QUERY_CYPHER] = result.get(
        "query"
    )

    state[QUERY_PARAMETERS] = dict(
        result.get(
            "parameters",
            {},
        )
        or {}
    )

    state[QUERY_RESULT] = list(
        result.get(
            "result",
            [],
        )
        or []
    )

    state[QUERY_RESULT_COUNT] = int(
        result.get(
            "result_count",
            0,
        )
        or 0
    )

    state[QUERY_ERROR] = result.get(
        "error_message"
    )

    state[QUERY_REPORT] = dict(
        result
    )


def _build_policy_error(
    cypher: str,
    parameters: Optional[dict],
    message: str,
    run_id: Optional[str],
    started_at: str,
    started_counter: float,
) -> Dict[str, Any]:
    """构建 Query Tool 策略拒绝结果。"""

    finished_at = _utc_now()

    duration_ms = (
        perf_counter()
        - started_counter
    ) * 1000

    report = {
        "status": "error",
        "query": (
            cypher.strip()
            if isinstance(cypher, str)
            else None
        ),
        "parameters": (
            dict(parameters)
            if isinstance(parameters, dict)
            else {}
        ),
        "result_count": 0,
        "result": [],
        "error_message": message,
        "error_code": "QUERY_POLICY_REJECTED",
        "runtime": {
            "run_id": run_id,
            "status": "error",
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": duration_ms,
        },
    }

    return report


def _record_runtime_policy_error(
    query_runtime: QueryRuntime,
    report: Dict[str, Any],
) -> None:
    """
    将策略拒绝记录到共享 QueryRuntime。

    策略拒绝发生在 QueryEngine 之前，因此不能调用
    QueryRuntime.execute()。这里直接更新其公开状态字段。
    """

    runtime = report.get(
        "runtime",
        {},
    )

    query_runtime.status = "error"

    query_runtime.run_id = runtime.get(
        "run_id"
    )

    query_runtime.started_at = runtime.get(
        "started_at"
    )

    query_runtime.finished_at = runtime.get(
        "finished_at"
    )

    query_runtime.duration_ms = runtime.get(
        "duration_ms"
    )

    query_runtime.cypher = report.get(
        "query"
    )

    query_runtime.parameters = dict(
        report.get(
            "parameters",
            {},
        )
        or {}
    )

    query_runtime.report = dict(
        report
    )

    query_runtime.query_state.update_from_report(
        report
    )


# ============================================================
# Query Validation
# ============================================================


def validate_agent_query(
    cypher: str,
    parameters: Optional[dict] = None,
) -> Dict[str, Any]:
    """
    验证 Agent 可以执行的 Cypher。

    Agent Query Tool 只允许只读查询。

    允许的起始语句：

        MATCH
        OPTIONAL MATCH
        WITH
        UNWIND
        RETURN
        SHOW
        PROFILE
        EXPLAIN

    明确拒绝写入或管理关键字，例如：

        CREATE
        MERGE
        DELETE
        SET
        REMOVE
        DROP
        LOAD
        CALL
        GRANT / DENY / REVOKE

    注意：

        这里是 Tool 层的保守安全策略，并不是完整 Cypher parser。
    """

    errors = []

    if not isinstance(
        cypher,
        str,
    ):
        errors.append(
            "cypher 必须是字符串。"
        )

    elif not cypher.strip():
        errors.append(
            "cypher 不能为空。"
        )

    if (
        parameters is not None
        and not isinstance(
            parameters,
            dict,
        )
    ):
        errors.append(
            "parameters 必须是 dict 或 None。"
        )

    if errors:
        return {
            "valid": False,
            "errors": errors,
        }

    normalized = cypher.strip()

    # Agent Tool 只允许单条 Cypher。
    if ";" in normalized:
        errors.append(
            "Agent Query Tool 不允许执行多条 Cypher 语句。"
        )

    # 为避免评论绕过起始关键词检查，保守禁止 Cypher 注释。
    if "//" in normalized or "/*" in normalized or "*/" in normalized:
        errors.append(
            "Agent Query Tool 暂不允许 Cypher 注释。"
        )

    sanitized = _strip_cypher_literals(
        normalized
    )

    write_pattern = r"\b(?:" + "|".join(
        re.escape(keyword)
        for keyword in sorted(
            WRITE_KEYWORDS
        )
    ) + r")\b"

    if re.search(
        write_pattern,
        sanitized,
        flags=re.IGNORECASE,
    ):
        errors.append(
            "Agent Query Tool 只允许只读 Cypher，检测到写入或管理操作。"
        )

    tokens = re.findall(
        r"[A-Za-z_][A-Za-z0-9_]*",
        sanitized,
    )

    if not tokens:
        errors.append(
            "无法识别 Cypher 起始关键字。"
        )
    else:
        first = tokens[0].upper()

        if first not in READ_ONLY_START_KEYWORDS:
            errors.append(
                "Agent Query Tool 仅允许只读查询，"
                "例如 MATCH / RETURN / SHOW / EXPLAIN / PROFILE。"
            )

        if first == "OPTIONAL":
            if len(tokens) < 2 or tokens[1].upper() != "MATCH":
                errors.append(
                    "OPTIONAL 后必须紧跟 MATCH。"
                )

    return {
        "valid": not errors,
        "errors": errors,
    }


# ============================================================
# ADK Function Tool Factory
# ============================================================


def make_query_knowledge_graph_tool(
    query_runtime: QueryRuntime,
) -> Callable[..., Dict[str, Any]]:
    """
    创建绑定指定 QueryRuntime 的 ADK Query Tool。

    返回的函数可直接放入：

        Agent(
            ...,
            tools=[query_knowledge_graph],
        )

    QueryRuntime 采用依赖注入，因此：

        Pipeline 版本
            ↓
        Pipeline.query_runtime

    和测试版本：

        FakeQueryRuntime

    都可以复用同一个 Tool。
    """

    if not isinstance(
        query_runtime,
        QueryRuntime,
    ):
        raise ToolInputError(
            "query_runtime 必须是 QueryRuntime 实例。"
        )

    def query_knowledge_graph(
        cypher: str,
        parameters: Optional[dict] = None,
        tool_context: ToolContext = None,
    ) -> Dict[str, Any]:
        """
        查询知识图谱并返回结果。

        只能执行只读 Cypher。

        推荐查询方式：

            MATCH (p:Product)
            RETURN p.product_name AS product_name
            LIMIT 10

        Args:
            cypher:
                要执行的只读 Cypher 查询。

            parameters:
                Cypher 参数，例如：
                {"limit": 10}

            tool_context:
                Google ADK ToolContext，由 ADK 自动注入。

        Returns:
            包含 status、query、parameters、result_count、result、
            error_message 和 runtime 的统一结果字典。
        """

        if tool_context is None:
            raise ToolExecutionError(
                "query_knowledge_graph 必须通过 ADK ToolContext 调用。"
            )

        run_id = getattr(
            tool_context,
            "invocation_id",
            None,
        )

        started_at = _utc_now()

        started_counter = perf_counter()

        validation = validate_agent_query(
            cypher,
            parameters,
        )

        if not validation["valid"]:
            report = _build_policy_error(
                cypher=cypher,
                parameters=parameters,
                message="; ".join(
                    validation["errors"]
                ),
                run_id=run_id,
                started_at=started_at,
                started_counter=started_counter,
            )

            _record_runtime_policy_error(
                query_runtime,
                report,
            )

            _sync_tool_context_state(
                tool_context,
                report,
            )

            return report

        normalized_parameters = _normalize_parameters(
            parameters
        )

        result = query_runtime.execute(
            cypher=cypher,
            parameters=normalized_parameters,
            run_id=run_id,
        )

        _sync_tool_context_state(
            tool_context,
            result,
        )

        return result

    query_knowledge_graph.__name__ = (
        "query_knowledge_graph"
    )

    query_knowledge_graph.__qualname__ = (
        "query_knowledge_graph"
    )

    return query_knowledge_graph


__all__ = [
    "READ_ONLY_START_KEYWORDS",
    "WRITE_KEYWORDS",
    "validate_agent_query",
    "make_query_knowledge_graph_tool",
]
