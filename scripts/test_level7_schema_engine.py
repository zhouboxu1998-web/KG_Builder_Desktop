"""
Phase 3 / Level 7

Schema Engine 测试。

测试目标：

    1. SchemaEngine 初始化。
    2. Schema Normalize。
    3. Node Schema Validation。
    4. Relationship Schema Validation。
    5. Relationship 引用不存在节点时能够发现错误。
    6. 空 Schema 能够发现错误。
    7. Schema Approval。
    8. Approved Schema Snapshot。
    9. Reset。
    10. 与 Phase 2 PipelineRuntime 完全独立。

本测试：

    不启动 LLM
    不启动 Google ADK Agent
    不连接 Neo4j
    不需要 API Key
"""


import sys

from pathlib import Path


# ============================================================
# Python Path
# ============================================================

ROOT = Path(
    __file__
).resolve().parents[1]

SRC = ROOT / "src"

sys.path.insert(
    0,
    str(SRC),
)


# ============================================================
# Imports
# ============================================================

from kg_builder.core.schema_engine import (
    SchemaEngine,
)


# ============================================================
# 测试数据
# ============================================================


VALID_PLAN = {
    "Product": {
        "construction_type": "node",
        "source_file": "products.csv",
        "label": "Product",
        "unique_column_name": "product_id",
        "properties": [
            "product_name",
            "price",
            "description",
        ],
    },

    "Assembly": {
        "construction_type": "node",
        "source_file": "assemblies.csv",
        "label": "Assembly",
        "unique_column_name": "assembly_id",
        "properties": [
            "assembly_name",
            "quantity",
            "product_id",
        ],
    },

    "PRODUCT_HAS_ASSEMBLY": {
        "construction_type": "relationship",
        "source_file": "assemblies.csv",
        "relationship_type": (
            "PRODUCT_HAS_ASSEMBLY"
        ),
        "from_node_label": "Product",
        "from_node_column": "product_id",
        "to_node_label": "Assembly",
        "to_node_column": "assembly_id",
        "properties": [],
    },
}


# ============================================================
# 1. Initialization
# ============================================================


def test_initialization():

    print(
        "\n"
        + "-" * 60
    )

    print(
        "1. SchemaEngine 初始化"
    )

    engine = SchemaEngine()

    assert (
        engine.status
        == "pending"
    )

    assert (
        engine.get_proposed_plan()
        == {}
    )

    assert (
        engine.get_normalized_plan()
        == {}
    )

    assert (
        engine.get_approved_plan()
        is None
    )

    print(
        "  ✅ SchemaEngine 初始状态正确"
    )


# ============================================================
# 2. Normalize
# ============================================================


def test_normalize():

    print(
        "\n"
        + "-" * 60
    )

    print(
        "2. Schema Normalize"
    )

    engine = SchemaEngine()

    normalized = (
        engine.set_proposed_plan(
            VALID_PLAN
        )
    )

    assert (
        "Product"
        in normalized
    )

    assert (
        "Assembly"
        in normalized
    )

    assert (
        "PRODUCT_HAS_ASSEMBLY"
        in normalized
    )

    assert (
        normalized["Product"][
            "construction_type"
        ]
        == "node"
    )

    assert isinstance(
        normalized["Product"][
            "properties"
        ],
        list,
    )

    print(
        "  ✅ Schema Normalize 正确"
    )


# ============================================================
# 3. Validation
# ============================================================


def test_validation():

    print(
        "\n"
        + "-" * 60
    )

    print(
        "3. Schema Validation"
    )

    engine = SchemaEngine()

    engine.set_proposed_plan(
        VALID_PLAN
    )

    result = (
        engine.validate()
    )

    assert result["valid"] is True

    assert (
        result["errors"]
        == []
    )

    print(
        "  ✅ 有效 Schema 验证通过"
    )

    print(
        f"  warnings: "
        f"{result['warnings']}"
    )


# ============================================================
# 4. Invalid Relationship
# ============================================================


def test_invalid_relationship():

    print(
        "\n"
        + "-" * 60
    )

    print(
        "4. Invalid Relationship"
    )

    invalid_plan = {
        "Product": {
            "construction_type": "node",
            "source_file": "products.csv",
            "label": "Product",
            "unique_column_name": "product_id",
            "properties": [],
        },

        "INVALID_RELATIONSHIP": {
            "construction_type": "relationship",
            "source_file": "bad.csv",
            "relationship_type": (
                "INVALID_RELATIONSHIP"
            ),
            "from_node_label": "Product",
            "from_node_column": "product_id",
            "to_node_label": "Supplier",
            "to_node_column": "supplier_id",
            "properties": [],
        },
    }

    engine = SchemaEngine()

    engine.set_proposed_plan(
        invalid_plan
    )

    result = (
        engine.validate()
    )

    assert result["valid"] is False

    assert any(
        "不存在的目标节点"
        in error
        for error in result[
            "errors"
        ]
    )

    print(
        "  ✅ 正确发现不存在的目标节点"
    )

    print(
        f"  errors: "
        f"{result['errors']}"
    )


# ============================================================
# 5. Invalid Node
# ============================================================


def test_invalid_node():

    print(
        "\n"
        + "-" * 60
    )

    print(
        "5. Invalid Node"
    )

    invalid_plan = {
        "Product": {
            "construction_type": "node",
            "source_file": "products.csv",
            "label": "Product",
            "properties": [],
        }
    }

    engine = SchemaEngine()

    engine.set_proposed_plan(
        invalid_plan
    )

    result = (
        engine.validate()
    )

    assert result["valid"] is False

    assert any(
        "unique_column_name"
        in error
        for error in result[
            "errors"
        ]
    )

    print(
        "  ✅ 正确发现节点缺少唯一标识字段"
    )


# ============================================================
# 6. Empty Schema
# ============================================================


def test_empty_schema():

    print(
        "\n"
        + "-" * 60
    )

    print(
        "6. Empty Schema"
    )

    engine = SchemaEngine()

    engine.set_proposed_plan(
        {}
    )

    result = (
        engine.validate()
    )

    assert result["valid"] is False

    assert len(
        result["errors"]
    ) > 0

    print(
        "  ✅ 空 Schema 被正确拒绝"
    )


# ============================================================
# 7. Approval
# ============================================================


def test_approval():

    print(
        "\n"
        + "-" * 60
    )

    print(
        "7. Schema Approval"
    )

    engine = SchemaEngine()

    engine.set_proposed_plan(
        VALID_PLAN
    )

    approved = (
        engine.approve()
    )

    assert (
        engine.status
        == "approved"
    )

    assert (
        engine.is_approved()
        is True
    )

    assert (
        approved
        == VALID_PLAN
    )

    print(
        "  ✅ Schema 批准成功"
    )


# ============================================================
# 8. Approval Reject
# ============================================================


def test_approval_reject():

    print(
        "\n"
        + "-" * 60
    )

    print(
        "8. Invalid Schema Approval"
    )

    invalid_plan = {
        "Product": {
            "construction_type": "node",
            "source_file": "products.csv",
            "label": "Product",
            "properties": [],
        }
    }

    engine = SchemaEngine()

    engine.set_proposed_plan(
        invalid_plan
    )

    try:

        engine.approve()

    except ValueError:

        print(
            "  ✅ 无效 Schema 无法批准"
        )

        return

    raise AssertionError(
        "无效 Schema 不应该被批准"
    )


# ============================================================
# 9. Snapshot
# ============================================================


def test_snapshot():

    print(
        "\n"
        + "-" * 60
    )

    print(
        "9. Schema Snapshot"
    )

    engine = SchemaEngine()

    engine.set_proposed_plan(
        VALID_PLAN
    )

    engine.approve()

    snapshot = (
        engine.get_snapshot()
    )

    assert (
        snapshot["status"]
        == "approved"
    )

    assert (
        snapshot["proposed"]
        == VALID_PLAN
    )

    assert (
        snapshot["normalized"]
        == VALID_PLAN
    )

    assert (
        snapshot["approved"]
        == VALID_PLAN
    )

    assert (
        snapshot["validation"][
            "valid"
        ]
        is True
    )

    print(
        "  ✅ Schema Snapshot 正确"
    )


# ============================================================
# 10. Reset
# ============================================================


def test_reset():

    print(
        "\n"
        + "-" * 60
    )

    print(
        "10. Schema Reset"
    )

    engine = SchemaEngine()

    engine.set_proposed_plan(
        VALID_PLAN
    )

    engine.approve()

    engine.reset()

    assert (
        engine.status
        == "pending"
    )

    assert (
        engine.get_proposed_plan()
        == {}
    )

    assert (
        engine.get_approved_plan()
        is None
    )

    print(
        "  ✅ SchemaEngine Reset 正确"
    )


# ============================================================
# Main
# ============================================================


def main():

    print(
        "=" * 60
    )

    print(
        "Phase 3 / Level 7"
    )

    print(
        "Schema Engine 测试"
    )

    print(
        "=" * 60
    )

    test_initialization()

    test_normalize()

    test_validation()

    test_invalid_relationship()

    test_invalid_node()

    test_empty_schema()

    test_approval()

    test_approval_reject()

    test_snapshot()

    test_reset()

    print(
        "\n"
        + "=" * 60
    )

    print(
        "🎉 Phase 3 / Level 7 全部通过！"
    )

    print(
        "=" * 60
    )


if __name__ == "__main__":
    main()

