"""Phase 4-B / Level 9：Pipeline → SchemaEngine → IngestionEngine 集成测试。

测试目标：

1. Pipeline 可以持有 SchemaEngine
2. Pipeline 可以持有 IngestionEngine
3. 未批准 Schema 时禁止 Build
4. 已批准 Schema 可以进入 IngestionEngine
5. Ingestion Report 可以回写 Pipeline State
6. Build 状态可以读取
7. Build 可以 reset

不需要：
- LLM
- API Key
- 真实 Neo4j
"""

import asyncio

from kg_builder.agents.pipeline import (
    KGBuilderPipeline,
)
from kg_builder.core.ingestion_engine import (
    IngestionEngine,
)


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
}


class FakeIngestionEngine:
    """模拟已经成功执行导入的 IngestionEngine。"""

    def __init__(self):
        self.status = "idle"
        self.calls = []

        self.report = {
            "status": "success",
            "nodes": {
                "Product": {
                    "status": "success",
                },
                "Assembly": {
                    "status": "success",
                },
            },
            "relationships": {},
            "validation": {
                "valid": True,
                "errors": [],
                "warnings": [],
            },
            "graph_validation": {
                "valid": True,
                "errors": [],
                "warnings": [],
            },
            "statistics": {
                "nodes": {
                    "Product": 10,
                    "Assembly": 5,
                },
                "relationships": {},
                "total_nodes": 15,
                "total_relationships": 0,
            },
        }

    def ingest(self, plan):
        self.calls.append(plan)

        self.status = "success"

        return {
            "status": "success",
            "report": self.report,
        }

    def get_report(self):
        return {
            **self.report,
            "status": self.status,
        }

    def reset(self):
        self.status = "idle"
        self.calls.clear()


async def test_initialization():
    pipeline = KGBuilderPipeline()

    assert pipeline.schema_engine is not None
    assert pipeline.ingestion_engine is not None

    assert isinstance(
        pipeline.ingestion_engine,
        IngestionEngine,
    )

    print("✅ 1. Pipeline initialization")


async def test_build_without_schema_approval():
    pipeline = KGBuilderPipeline()

    fake_engine = FakeIngestionEngine()

    pipeline.ingestion_engine = fake_engine

    result = await pipeline.build()

    assert result["status"] == "error"

    assert (
        "Schema 尚未批准"
        in result["message"]
    )

    assert fake_engine.calls == []

    print(
        "✅ 2. build blocked without schema approval"
    )


async def test_build_with_approved_schema():
    pipeline = KGBuilderPipeline()

    fake_engine = FakeIngestionEngine()

    pipeline.ingestion_engine = fake_engine

    pipeline.schema_engine.set_proposed_plan(
        VALID_PLAN
    )

    approved = pipeline.schema_engine.approve()

    assert approved == VALID_PLAN

    assert (
        pipeline.schema_engine.is_approved()
        is True
    )

    result = await pipeline.build()

    assert result["status"] == "success"

    assert len(fake_engine.calls) == 1

    assert (
        fake_engine.calls[0]
        == VALID_PLAN
    )

    print(
        "✅ 3. approved schema reaches ingestion engine"
    )


async def test_build_state():
    pipeline = KGBuilderPipeline()

    fake_engine = FakeIngestionEngine()

    pipeline.ingestion_engine = fake_engine

    pipeline.schema_engine.set_proposed_plan(
        VALID_PLAN
    )

    pipeline.schema_engine.approve()

    result = await pipeline.build()

    assert result["status"] == "success"

    state = await pipeline.get_build_state()

    assert (
        state["ingestion_status"]
        == "success"
    )

    assert (
        state["ingestion_report"]["status"]
        == "success"
    )

    assert (
        state["ingestion_stats"][
            "total_nodes"
        ]
        == 15
    )

    print("✅ 4. ingestion state persisted")


async def test_get_ingestion_report():
    pipeline = KGBuilderPipeline()

    fake_engine = FakeIngestionEngine()

    pipeline.ingestion_engine = fake_engine

    pipeline.schema_engine.set_proposed_plan(
        VALID_PLAN
    )

    pipeline.schema_engine.approve()

    await pipeline.build()

    report = pipeline.get_ingestion_report()

    assert (
        report["status"]
        == "success"
    )

    assert (
        report["statistics"][
            "total_nodes"
        ]
        == 15
    )

    print(
        "✅ 5. ingestion report"
    )


async def test_reset_build():
    pipeline = KGBuilderPipeline()

    fake_engine = FakeIngestionEngine()

    pipeline.ingestion_engine = fake_engine

    pipeline.schema_engine.set_proposed_plan(
        VALID_PLAN
    )

    pipeline.schema_engine.approve()

    await pipeline.build()

    assert (
        fake_engine.status
        == "success"
    )

    pipeline.reset_build()

    assert (
        fake_engine.status
        == "idle"
    )

    state = await pipeline.get_build_state()

    assert state == {}

    print("✅ 6. reset build")


async def test_full_reset():
    pipeline = KGBuilderPipeline()

    fake_engine = FakeIngestionEngine()

    pipeline.ingestion_engine = fake_engine

    pipeline.schema_engine.set_proposed_plan(
        VALID_PLAN
    )

    pipeline.schema_engine.approve()

    await pipeline.build()

    pipeline.reset()

    assert (
        pipeline.schema_engine.is_approved()
        is False
    )

    assert (
        fake_engine.status
        == "idle"
    )

    assert (
        pipeline.get_ingestion_report()[
            "status"
        ]
        == "idle"
    )

    print("✅ 7. full reset")


async def main():
    await test_initialization()
    await test_build_without_schema_approval()
    await test_build_with_approved_schema()
    await test_build_state()
    await test_get_ingestion_report()
    await test_reset_build()
    await test_full_reset()

    print()
    print(
        "🎉 Phase 4-B / Level 9 全部通过！"
    )


if __name__ == "__main__":
    asyncio.run(main())