"""Phase 4 / Level 8：IngestionEngine 单元测试。

测试目标：

1. 初始化
2. Schema Normalize
3. CSV Header Validation
4. Schema Validation
5. Constraint
6. Node Import
7. Relationship Import
8. Statistics
9. Full Ingestion
10. Reset

本测试不要求真实 Neo4j。
"""

from pathlib import Path
import tempfile

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
    "PRODUCT_HAS_ASSEMBLY": {
        "construction_type": "relationship",
        "source_file": "assembly_parts.csv",
        "relationship_type": "PRODUCT_HAS_ASSEMBLY",
        "from_node_label": "Product",
        "from_node_column": "product_id",
        "to_node_label": "Assembly",
        "to_node_column": "assembly_id",
        "properties": [
            "quantity",
        ],
    },
}


class FakeNeo4jClient:
    """用于测试的 Neo4j Client。"""

    def __init__(self):
        self.queries = []

    def send_query(
        self,
        cypher: str,
        parameters=None,
    ):
        self.queries.append(
            {
                "cypher": cypher,
                "parameters": parameters or {},
            }
        )

        if "count(n)" in cypher:
            return {
                "status": "success",
                "query_result": [
                    {"count": 10}
                ],
            }

        if "count(r)" in cypher:
            return {
                "status": "success",
                "query_result": [
                    {"count": 15}
                ],
            }

        return {
            "status": "success",
            "query_result": [],
        }


def create_csv(
    directory: Path,
    filename: str,
    header: list[str],
):
    path = directory / filename

    path.write_text(
        ",".join(header) + "\n",
        encoding="utf-8",
    )

    return path


def test_initialization():
    engine = IngestionEngine(
        neo4j_client=FakeNeo4jClient()
    )

    assert engine.status == "idle"

    report = engine.get_report()

    assert report["status"] == "idle"

    print("✅ 1. initialization")


def test_normalize():
    engine = IngestionEngine(
        neo4j_client=FakeNeo4jClient()
    )

    plan = {
        " Product ": {
            "construction_type": " NODE ",
            "label": " Product ",
            "unique_column_name": " product_id ",
        }
    }

    normalized = engine.normalize_plan(
        plan
    )

    assert "Product" in normalized

    assert (
        normalized["Product"][
            "construction_type"
        ]
        == "node"
    )

    assert (
        normalized["Product"]["label"]
        == "Product"
    )

    assert (
        normalized["Product"][
            "unique_column_name"
        ]
        == "product_id"
    )

    print("✅ 2. normalize")


def test_csv_header_validation():
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)

        create_csv(
            directory,
            "products.csv",
            [
                "product_id",
                "product_name",
                "price",
            ],
        )

        engine = IngestionEngine(
            neo4j_client=FakeNeo4jClient()
        )

        # 临时让当前工作目录成为 CSV 查找位置
        import os

        old_cwd = os.getcwd()

        try:
            os.chdir(directory)

            result = engine.inspect_csv(
                "products.csv",
                [
                    "product_id",
                    "product_name",
                ],
            )

            assert result["exists"] is True
            assert result["valid"] is True

            result = engine.inspect_csv(
                "products.csv",
                [
                    "product_id",
                    "description",
                ],
            )

            assert result["valid"] is False
            assert "description" in result[
                "missing_columns"
            ]

        finally:
            os.chdir(old_cwd)

    print("✅ 3. CSV header validation")


def test_schema_validation():
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)

        create_csv(
            directory,
            "products.csv",
            [
                "product_id",
                "product_name",
                "price",
                "description",
            ],
        )

        create_csv(
            directory,
            "assemblies.csv",
            [
                "assembly_id",
                "assembly_name",
                "quantity",
                "product_id",
            ],
        )

        create_csv(
            directory,
            "assembly_parts.csv",
            [
                "product_id",
                "assembly_id",
                "quantity",
            ],
        )

        import os

        old_cwd = os.getcwd()

        try:
            os.chdir(directory)

            engine = IngestionEngine(
                neo4j_client=FakeNeo4jClient()
            )

            validation = engine.validate_plan(
                VALID_PLAN
            )

            assert validation["valid"] is True
            assert validation["errors"] == []
            assert (
                validation["node_count"]
                == 2
            )
            assert (
                validation[
                    "relationship_count"
                ]
                == 1
            )

        finally:
            os.chdir(old_cwd)

    print("✅ 4. schema validation")


def test_invalid_schema():
    engine = IngestionEngine(
        neo4j_client=FakeNeo4jClient()
    )

    invalid_plan = {
        "BadRelationship": {
            "construction_type": "relationship",
            "source_file": "x.csv",
            "relationship_type": "USES",
            "from_node_label": "Product",
            "from_node_column": "product_id",
            "to_node_label": "MissingNode",
            "to_node_column": "id",
        }
    }

    validation = engine.validate_plan(
        invalid_plan
    )

    assert validation["valid"] is False

    assert any(
        "MissingNode" in error
        for error in validation["errors"]
    )

    print("✅ 5. invalid schema")


def test_constraint():
    fake = FakeNeo4jClient()

    engine = IngestionEngine(
        neo4j_client=fake
    )

    plan = {
        "Product": VALID_PLAN["Product"]
    }

    result = engine.create_constraints(
        plan
    )

    assert result["status"] == "success"
    assert len(result["created"]) == 1

    assert len(fake.queries) == 1

    print("✅ 6. constraint")


def test_node_import():
    fake = FakeNeo4jClient()

    engine = IngestionEngine(
        neo4j_client=fake
    )

    result = engine.import_node(
        VALID_PLAN["Product"]
    )

    assert result["status"] == "success"

    assert len(fake.queries) == 1

    query = fake.queries[0]["cypher"]

    assert "LOAD CSV" in query
    assert "MERGE" in query

    print("✅ 7. node import")


def test_relationship_import():
    fake = FakeNeo4jClient()

    engine = IngestionEngine(
        neo4j_client=fake
    )

    result = engine.import_relationship(
        VALID_PLAN[
            "PRODUCT_HAS_ASSEMBLY"
        ]
    )

    assert result["status"] == "success"

    assert len(fake.queries) == 1

    query = fake.queries[0]["cypher"]
    parameters = fake.queries[0]["parameters"]

    # Neo4j 使用动态关系类型：
    # $($relationship_type)
    # 因此具体关系名称不直接出现在 Cypher 中，
    # 而是通过 parameters 传入。
    assert "$($relationship_type)" in query

    assert (
        parameters["relationship_type"]
        == "PRODUCT_HAS_ASSEMBLY"
    )

    assert (
        parameters["from_node_label"]
        == "Product"
    )

    assert (
        parameters["to_node_label"]
        == "Assembly"
    )

    assert (
        parameters["from_node_column"]
        == "product_id"
    )

    assert (
        parameters["to_node_column"]
        == "assembly_id"
    )

    assert "MATCH" in query
    assert "MERGE" in query

    print("✅ 8. relationship import")


def test_statistics():
    fake = FakeNeo4jClient()

    engine = IngestionEngine(
        neo4j_client=fake
    )

    statistics = engine.collect_statistics(
        VALID_PLAN
    )

    assert (
        statistics["nodes"]["Assembly"]
        == 10
    )

    assert (
        statistics["nodes"]["Product"]
        == 10
    )

    assert (
        statistics[
            "relationships"
        ]["PRODUCT_HAS_ASSEMBLY"]
        == 15
    )

    assert statistics["total_nodes"] == 20
    assert (
        statistics["total_relationships"]
        == 15
    )

    print("✅ 9. statistics")


def test_reset():
    fake = FakeNeo4jClient()

    engine = IngestionEngine(
        neo4j_client=fake
    )

    engine.status = "success"

    engine.reset()

    assert engine.status == "idle"

    report = engine.get_report()

    assert report["status"] == "idle"

    print("✅ 10. reset")


def main():
    test_initialization()
    test_normalize()
    test_csv_header_validation()
    test_schema_validation()
    test_invalid_schema()
    test_constraint()
    test_node_import()
    test_relationship_import()
    test_statistics()
    test_reset()

    print()
    print(
        "🎉 Phase 4 / Level 8 全部通过！"
    )


if __name__ == "__main__":
    main()