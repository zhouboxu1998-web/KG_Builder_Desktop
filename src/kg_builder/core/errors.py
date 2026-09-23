"""
KG Builder 统一异常体系。

设计目标：

    让 Agent、Tool、Neo4j、Schema、Entity Resolution、Pipeline
    等不同层级使用明确的异常边界，而不是把所有错误都当成
    ``Exception`` 或 ``RuntimeError``。

继承设计保留常见 Python builtin exception 的兼容性：

    SchemaValidationError -> ValueError
    QueryValidationError  -> ValueError
    ToolInputError        -> TypeError
    PipelineError         -> RuntimeError
    AgentExecutionError   -> RuntimeError
    Neo4jError             -> RuntimeError

这样旧代码中已有的：

    except ValueError
    except RuntimeError

仍然可以继续工作。
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class KGBuilderError(Exception):
    """KG Builder 所有业务异常的根类。"""

    default_code = "KG_BUILDER_ERROR"

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message)

        self.message = message
        self.code = code or self.default_code
        self.details = dict(details or {})
        self.cause = cause

    def to_dict(self) -> Dict[str, Any]:
        """转换成可用于日志、Runtime Event、Tool Result 的字典。"""

        return {
            "error_code": self.code,
            "error_type": self.__class__.__name__,
            "error_message": self.message,
            "details": dict(self.details),
        }

    @classmethod
    def from_exception(
        cls,
        error: BaseException,
        *,
        message: Optional[str] = None,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> "KGBuilderError":
        """将底层异常包装为当前 KG Builder 异常类型。"""

        return cls(
            message or str(error) or error.__class__.__name__,
            code=code,
            details=details,
            cause=error,
        )


# ============================================================
# Configuration
# ============================================================


class ConfigurationError(KGBuilderError, ValueError):
    """配置错误。"""

    default_code = "CONFIGURATION_ERROR"


# ============================================================
# LLM / Agent
# ============================================================


class LLMError(KGBuilderError, RuntimeError):
    """LLM 调用或 LLM 返回结果错误。"""

    default_code = "LLM_ERROR"


class AgentExecutionError(KGBuilderError, RuntimeError):
    """Agent 执行过程中的错误。"""

    default_code = "AGENT_EXECUTION_ERROR"


# ============================================================
# Tool
# ============================================================


class ToolExecutionError(KGBuilderError, RuntimeError):
    """Tool 执行错误。"""

    default_code = "TOOL_EXECUTION_ERROR"


class ToolInputError(ToolExecutionError, TypeError):
    """Tool 输入参数类型或结构错误。"""

    default_code = "TOOL_INPUT_ERROR"


# ============================================================
# Neo4j
# ============================================================


class Neo4jError(KGBuilderError, RuntimeError):
    """Neo4j 相关错误的根类。"""

    default_code = "NEO4J_ERROR"


class Neo4jConnectionError(Neo4jError):
    """Neo4j Driver / Session / Connection 错误。"""

    default_code = "NEO4J_CONNECTION_ERROR"


class Neo4jQueryError(Neo4jError):
    """Neo4j Cypher 执行错误。"""

    default_code = "NEO4J_QUERY_ERROR"


# ============================================================
# Schema
# ============================================================


class SchemaValidationError(KGBuilderError, ValueError):
    """Schema 结构或规则验证错误。"""

    default_code = "SCHEMA_VALIDATION_ERROR"


# ============================================================
# Query
# ============================================================


class QueryValidationError(KGBuilderError, ValueError):
    """Query 请求格式错误。"""

    default_code = "QUERY_VALIDATION_ERROR"


class QueryExecutionError(KGBuilderError, RuntimeError):
    """Query 执行过程中的业务错误。"""

    default_code = "QUERY_EXECUTION_ERROR"


class QueryRuntimeError(QueryExecutionError):
    """Query Runtime 生命周期或依赖错误。"""

    default_code = "QUERY_RUNTIME_ERROR"


# ============================================================
# Entity Resolution
# ============================================================


class EntityResolutionError(KGBuilderError, RuntimeError):
    """实体解析错误。"""

    default_code = "ENTITY_RESOLUTION_ERROR"


# ============================================================
# Ingestion / Pipeline
# ============================================================


class IngestionError(KGBuilderError, RuntimeError):
    """知识图谱数据摄取错误。"""

    default_code = "INGESTION_ERROR"


class PipelineError(KGBuilderError, RuntimeError):
    """Pipeline 生命周期或阶段执行错误。"""

    default_code = "PIPELINE_ERROR"


class OperationTimeoutError(KGBuilderError, TimeoutError):
    """操作超时。"""

    default_code = "OPERATION_TIMEOUT"


class RetryExhaustedError(KGBuilderError, RuntimeError):
    """可重试操作达到最大尝试次数后仍然失败。"""

    default_code = "RETRY_EXHAUSTED"


__all__ = [
    "KGBuilderError",
    "ConfigurationError",
    "LLMError",
    "AgentExecutionError",
    "ToolExecutionError",
    "ToolInputError",
    "Neo4jError",
    "Neo4jConnectionError",
    "Neo4jQueryError",
    "SchemaValidationError",
    "QueryValidationError",
    "QueryExecutionError",
    "QueryRuntimeError",
    "EntityResolutionError",
    "IngestionError",
    "PipelineError",
    "OperationTimeoutError",
    "RetryExhaustedError",
]
