"""
Phase 4 Final Integration Test

验证完整的 Knowledge Graph Ingestion 工作流：

    SchemaEngine
        ↓
    Schema Approval
        ↓
    Build
        ↓
    IngestionEngine
        ↓
    Ingestion Report
        ↓
    Build State
        ↓
    PipelineRuntime
"""

import asyncio

from kg_builder.agents.pipeline import KGBuilderPipeline
from kg_builder.state import (
    INGESTION_STATUS,
    INGESTION_REPORT,
    INGESTION_ERRORS,
    INGESTION_WARNINGS,
    INGESTION_STATS,
)


# ============================================================
# Fake IngestionEngine
# ============================================================


class FakeIngestionEngine:
    """
    Phase 4 集成测试使用的 IngestionEngine。

    用来验证 Pipeline 的编排逻辑，
    不连接真实 Neo4j。
    """

    def __init__(
        self,
        status: str = "success",
    ):
        self.status = status

        self.ingest_called = False
        self.received_plan = None

        self._report = {
            "status": status,
            "validation": {
                "errors": [],
                "warnings": [],
            },
            "graph_validation": {
                "errors": [],
                "warnings": [],
            },
            "statistics": {
                "nodes_created": 3,
                "relationships_created": 2,
            },
        }

    def ingest(
        self,
        plan,
    ):
        self.ingest_called = True
        self.received_plan = plan

        return {
            "status": self.status,
            "report": self._report,
        }

    def get_report(self):
        return self._report

    def reset(self):
        self.status = "success"
        self.ingest_called = False
        self.received_plan = None
        self._report = {}

    # ============================================================
# 测试 Schema
# ============================================================


def make_test_schema():
    return {
        "Product": {
            "construction_type": "node",
            "label": "Product",
            "unique_column_name": "product_id",
            "properties": [
                "product_name",
            ],
        },
        "Supplier": {
            "construction_type": "node",
            "label": "Supplier",
            "unique_column_name": "supplier_id",
            "properties": [
                "supplier_name",
            ],
        },
        "SUPPLIES": {
            "construction_type": "relationship",
            "relationship_type": "SUPPLIES",
            "from_node_label": "Supplier",  # ← 改名
            "from_node_column": "supplier_id",
            "to_node_label": "Product",  # ← 改名
            "to_node_column": "product_id",
            "properties": [],
        },
    }


# ============================================================
# 1. 初始化
# ============================================================


async def test_initialization():

    pipeline = KGBuilderPipeline()

    assert (
        pipeline.schema_engine.is_approved()
        is False
    )

    assert (
        pipeline.runtime.status
        == "idle"
    )

    print(
        "✅ 1. Pipeline initialization"
    )


# ============================================================
# 2. 未批准 Schema 时禁止 Build
# ============================================================


async def test_build_blocked_without_schema():

    pipeline = KGBuilderPipeline()

    pipeline.start_run(
        metadata={
            "mode": "phase4_integration",
        }
    )

    fake_engine = FakeIngestionEngine()

    pipeline.ingestion_engine = (
        fake_engine
    )

    result = await pipeline.build()

    assert (
        result["status"]
        == "error"
    )

    assert (
        fake_engine.ingest_called
        is False
    )

    print(
        "✅ 2. Build blocked without "
        "approved schema"
    )


# ============================================================
# 3. Schema Normalize + Validate + Approve
# ============================================================


async def test_schema_approval():

    pipeline = KGBuilderPipeline()

    schema = make_test_schema()

    pipeline.schema_engine.set_proposed_plan(
        schema
    )

    normalized = (
        pipeline.schema_engine
        .get_normalized_plan()
    )

    assert normalized

    validation = (
        pipeline.schema_engine.validate()
    )

    print("validation =", validation)
    print("type(validation['valid']) =", type(validation.get("valid")))
    print("repr(validation['valid']) =", repr(validation.get("valid")))

    assert (
            validation["valid"]
            is True
    ), f"validation['valid'] = {validation['valid']!r}, 完整 validation = {validation}"

    approved = (
        pipeline.schema_engine.approve()
    )

    assert approved

    assert (
        pipeline.schema_engine
        .is_approved()
        is True
    )

    print(
        "✅ 3. Schema normalized, "
        "validated and approved"
    )


# ============================================================
# 4. Build 将 approved schema 传递给 IngestionEngine
# ============================================================


async def test_schema_reaches_ingestion():

    pipeline = KGBuilderPipeline()

    pipeline.start_run(
        metadata={
            "mode": "phase4_integration",
        }
    )

    schema = make_test_schema()

    pipeline.schema_engine.set_proposed_plan(
        schema
    )

    pipeline.schema_engine.approve()

    fake_engine = (
        FakeIngestionEngine(
            status="success"
        )
    )

    pipeline.ingestion_engine = (
        fake_engine
    )

    result = await pipeline.build()

    assert (
        result["status"]
        == "success"
    )

    assert (
        fake_engine.ingest_called
        is True
    )

    assert (
        fake_engine.received_plan
        is not None
    )

    assert (
        fake_engine.received_plan
        == pipeline.schema_engine
        .get_approved_plan()
    )

    print(
        "✅ 4. Approved schema reached "
        "IngestionEngine"
    )


# ============================================================
# 5. Ingestion Result 写入 Build State
# ============================================================


async def test_build_state():

    pipeline = KGBuilderPipeline()

    pipeline.start_run(
        metadata={
            "mode": "phase4_integration",
        }
    )

    pipeline.schema_engine.set_proposed_plan(
        make_test_schema()
    )

    pipeline.schema_engine.approve()

    pipeline.ingestion_engine = (
        FakeIngestionEngine(
            status="success"
        )
    )

    result = await pipeline.build()

    assert (
        result["status"]
        == "success"
    )

    state = await (
        pipeline.get_build_state()
    )

    assert (
        state[INGESTION_STATUS]
        == "success"
    )

    assert (
        INGESTION_REPORT
        in state
    )

    assert (
        INGESTION_ERRORS
        in state
    )

    assert (
        INGESTION_WARNINGS
        in state
    )

    assert (
        INGESTION_STATS
        in state
    )

    print(
        "✅ 5. Ingestion state persisted"
    )


# ============================================================
# 6. Runtime success
# ============================================================


async def test_runtime_success():

    pipeline = KGBuilderPipeline()

    pipeline.start_run(
        metadata={
            "mode": "phase4_runtime",
        }
    )

    pipeline.schema_engine.set_proposed_plan(
        make_test_schema()
    )

    pipeline.schema_engine.approve()

    pipeline.ingestion_engine = (
        FakeIngestionEngine(
            status="success"
        )
    )

    await pipeline.build()

    assert (
        pipeline.runtime.status
        == "running"
    )

    assert (
        pipeline.runtime.current_stage
        is None
    )

    print(
        "✅ 6. Build Runtime finished "
        "with success"
    )


# ============================================================
# 7. Runtime error
# ============================================================


async def test_runtime_error():

    pipeline = KGBuilderPipeline()

    pipeline.start_run(
        metadata={
            "mode": "phase4_runtime_error",
        }
    )

    pipeline.schema_engine.set_proposed_plan(
        make_test_schema()
    )

    pipeline.schema_engine.approve()

    pipeline.ingestion_engine = (
        FakeIngestionEngine(
            status="error"
        )
    )

    result = await pipeline.build()

    assert (
        result["status"]
        == "error"
    )

    assert (
        pipeline.runtime.status
        == "running"
    )

    assert (
        pipeline.runtime.current_stage
        is None
    )

    print(
        "✅ 7. Build Runtime handled "
        "ingestion error"
    )


# ============================================================
# 8. Build State 与 Runtime 不混合
# ============================================================


async def test_state_separation():

    pipeline = KGBuilderPipeline()

    pipeline.start_run(
        metadata={
            "mode": "phase4_state_separation",
        }
    )

    pipeline.schema_engine.set_proposed_plan(
        make_test_schema()
    )

    pipeline.schema_engine.approve()

    pipeline.ingestion_engine = (
        FakeIngestionEngine(
            status="success"
        )
    )

    await pipeline.build()

    build_state = await (
        pipeline.get_build_state()
    )

    runtime_summary = (
        pipeline.get_run_summary()
    )

    assert (
        INGESTION_STATUS
        in build_state
    )

    assert (
        "run_id"
        in runtime_summary
    )

    print(
        "✅ 8. Pipeline state and "
        "Runtime state remain separated"
    )


# ============================================================
# 9. Reset
# ============================================================


async def test_reset():

    pipeline = KGBuilderPipeline()

    pipeline.start_run(
        metadata={
            "mode": "phase4_reset",
        }
    )

    pipeline.schema_engine.set_proposed_plan(
        make_test_schema()
    )

    pipeline.schema_engine.approve()

    pipeline.ingestion_engine = (
        FakeIngestionEngine(
            status="success"
        )
    )

    await pipeline.build()

    pipeline.reset()

    assert (
        pipeline.schema_engine
        .is_approved()
        is False
    )

    assert (
        pipeline.get_ingestion_report()
        == {}
    )

    state = await (
        pipeline.get_build_state()
    )

    assert state == {}

    print(
        "✅ 9. Phase 4 reset"
    )


# ============================================================
# Main
# ============================================================


async def main():

    print()
    print("=" * 60)
    print(
        "Phase 4 Final Integration Test"
    )
    print("=" * 60)
    print()

    await test_initialization()

    await (
        test_build_blocked_without_schema()
    )

    await test_schema_approval()

    await (
        test_schema_reaches_ingestion()
    )

    await test_build_state()

    await test_runtime_success()

    await test_runtime_error()

    await test_state_separation()

    await test_reset()

    print()
    print("=" * 60)
    print(
        "🎉 Phase 4 Final Integration Test "
        "全部通过"
    )
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(
        main()
    )