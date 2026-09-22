"""结构化图谱：Schema 提议、验证与移除工具。"""

from google.adk.tools import ToolContext

from kg_builder.core.neo4j_client import (
    tool_error,
    tool_success,
)

from kg_builder.core.schema_engine import (
    SchemaEngine,
)

from kg_builder.state import (
    PROPOSED_CONSTRUCTION_PLAN,
    SCHEMA_NORMALIZED_PLAN,
    SCHEMA_VALIDATION,
    SCHEMA_VALIDATION_FEEDBACK,
    SCHEMA_STATUS,
)

from kg_builder.tools.file_tools import (
    search_file,
)


# ============================================================
# 读取当前 Schema
# ============================================================


def get_proposed_construction_plan(
    tool_context: ToolContext,
) -> dict:
    """
    获取当前 Agent 提议的构建计划。
    """

    return tool_context.state.get(
        PROPOSED_CONSTRUCTION_PLAN,
        {},
    )


# ============================================================
# 提议 Node
# ============================================================


def propose_node_construction(
    approved_file: str,
    proposed_label: str,
    unique_column_name: str,
    proposed_properties: list,
    tool_context: ToolContext,
) -> dict:
    """
    提议一个节点构建规则。
    """

    result = search_file(
        approved_file,
        unique_column_name,
    )

    if result["status"] == "error":

        return result

    if (
        result["search_results"]
        ["metadata"]
        ["lines_found"]
        == 0
    ):

        return tool_error(
            f"{approved_file} 中不存在列 "
            f"{unique_column_name}"
        )

    plan = tool_context.state.get(
        PROPOSED_CONSTRUCTION_PLAN,
        {},
    )

    rule = {
        "construction_type": "node",
        "source_file": approved_file,
        "label": proposed_label,
        "unique_column_name": (
            unique_column_name
        ),
        "properties": proposed_properties,
    }

    plan[proposed_label] = rule

    tool_context.state[
        PROPOSED_CONSTRUCTION_PLAN
    ] = plan

    # --------------------------------------------------------
    # Phase 3
    #
    # 每次 Schema 修改以后，
    # 都重新生成 normalized plan。
    #
    # 注意：
    # 这里只做 normalize，
    # 不自动 approve。
    # --------------------------------------------------------

    engine = SchemaEngine()

    normalized = (
        engine.normalize_plan(
            plan
        )
    )

    tool_context.state[
        SCHEMA_NORMALIZED_PLAN
    ] = normalized

    tool_context.state[
        SCHEMA_STATUS
    ] = "proposed"

    return tool_success(
        "node_construction",
        rule,
    )


# ============================================================
# 提议 Relationship
# ============================================================


def propose_relationship_construction(
    approved_file: str,
    proposed_relationship_type: str,
    from_node_label: str,
    from_node_column: str,
    to_node_label: str,
    to_node_column: str,
    proposed_properties: list,
    tool_context: ToolContext,
) -> dict:
    """
    提议一个关系构建规则。
    """

    for col in (
        from_node_column,
        to_node_column,
    ):

        result = search_file(
            approved_file,
            col,
        )

        if result["status"] == "error":

            return result

        if (
            result["search_results"]
            ["metadata"]
            ["lines_found"]
            == 0
        ):

            return tool_error(
                f"{approved_file} 中不存在列 "
                f"{col}"
            )

    plan = tool_context.state.get(
        PROPOSED_CONSTRUCTION_PLAN,
        {},
    )

    rule = {
        "construction_type": "relationship",
        "source_file": approved_file,
        "relationship_type": (
            proposed_relationship_type
        ),
        "from_node_label": (
            from_node_label
        ),
        "from_node_column": (
            from_node_column
        ),
        "to_node_label": (
            to_node_label
        ),
        "to_node_column": (
            to_node_column
        ),
        "properties": proposed_properties,
    }

    plan[
        proposed_relationship_type
    ] = rule

    tool_context.state[
        PROPOSED_CONSTRUCTION_PLAN
    ] = plan

    # Phase 3 Normalize

    engine = SchemaEngine()

    normalized = (
        engine.normalize_plan(
            plan
        )
    )

    tool_context.state[
        SCHEMA_NORMALIZED_PLAN
    ] = normalized

    tool_context.state[
        SCHEMA_STATUS
    ] = "proposed"

    return tool_success(
        "relationship_construction",
        rule,
    )


# ============================================================
# Schema Validate
# ============================================================


def validate_proposed_schema(
    tool_context: ToolContext,
) -> dict:
    """
    使用 SchemaEngine 对当前 Schema 做确定性结构验证。

    注意：

        验证不等于批准。

        valid == True
        只代表 Schema 通过结构检查。

        approve 仍然由 Pipeline 控制。
    """

    plan = tool_context.state.get(
        PROPOSED_CONSTRUCTION_PLAN,
        {},
    )

    if not plan:

        return tool_error(
            "当前没有可验证的 Schema。"
        )

    engine = SchemaEngine()

    engine.set_proposed_plan(
        plan
    )

    validation = engine.validate()

    normalized = (
        engine.get_normalized_plan()
    )

    tool_context.state[
        SCHEMA_NORMALIZED_PLAN
    ] = normalized

    tool_context.state[
        SCHEMA_VALIDATION
    ] = validation

    tool_context.state[
        SCHEMA_VALIDATION_FEEDBACK
    ] = list(
        validation["errors"]
    )

    if validation["valid"]:

        tool_context.state[
            SCHEMA_STATUS
        ] = "validated"

    else:

        tool_context.state[
            SCHEMA_STATUS
        ] = "rejected"

    return tool_success(
        "schema_validation",
        validation,
    )


# ============================================================
# Remove Node
# ============================================================


def remove_node_construction(
    node_label: str,
    tool_context: ToolContext,
) -> dict:
    """
    移除一个节点构建规则。
    """

    plan = tool_context.state.get(
        PROPOSED_CONSTRUCTION_PLAN,
        {},
    )

    if node_label not in plan:

        return tool_success(
            "message",
            "未找到该节点构建规则，无需移除。",
        )

    del plan[node_label]

    tool_context.state[
        PROPOSED_CONSTRUCTION_PLAN
    ] = plan

    # 重新 Normalize

    engine = SchemaEngine()

    tool_context.state[
        SCHEMA_NORMALIZED_PLAN
    ] = engine.normalize_plan(
        plan
    )

    return tool_success(
        "node_construction_removed",
        node_label,
    )


# ============================================================
# Remove Relationship
# ============================================================


def remove_relationship_construction(
    relationship_type: str,
    tool_context: ToolContext,
) -> dict:
    """
    移除一个关系构建规则。
    """

    plan = tool_context.state.get(
        PROPOSED_CONSTRUCTION_PLAN,
        {},
    )

    if relationship_type not in plan:

        return tool_success(
            "message",
            "未找到该关系构建规则，无需移除。",
        )

    plan.pop(
        relationship_type
    )

    tool_context.state[
        PROPOSED_CONSTRUCTION_PLAN
    ] = plan

    # 重新 Normalize

    engine = SchemaEngine()

    tool_context.state[
        SCHEMA_NORMALIZED_PLAN
    ] = engine.normalize_plan(
        plan
    )

    return tool_success(
        "relationship_construction_removed",
        relationship_type,
    )


__all__ = [
    "get_proposed_construction_plan",
    "propose_node_construction",
    "propose_relationship_construction",
    "validate_proposed_schema",
    "remove_node_construction",
    "remove_relationship_construction",
]
