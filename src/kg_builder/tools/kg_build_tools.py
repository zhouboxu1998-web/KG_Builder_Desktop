"""结构化图谱构建工具。

Phase 4：
    旧版构建 API 继续保留，
    实际导入逻辑统一交给 IngestionEngine。
"""

from typing import Any, Dict, List

from kg_builder.core.ingestion_engine import IngestionEngine
from kg_builder.core.neo4j_client import graphdb


def create_uniqueness_constraint(
    label: str,
    unique_property_key: str,
) -> Dict[str, Any]:
    """创建 Neo4j 唯一约束。

    保留旧接口，供已有代码继续使用。
    """

    constraint_name = (
        f"{label}_{unique_property_key}_constraint"
    )

    query = f"""
    CREATE CONSTRAINT `{constraint_name}`
    IF NOT EXISTS
    FOR (n:`{label}`)
    REQUIRE n.`{unique_property_key}` IS UNIQUE
    """

    return graphdb.send_query(query)


def load_nodes_from_csv(
    source_file: str,
    label: str,
    unique_column_name: str,
    properties: List[str],
) -> Dict[str, Any]:
    """从 CSV 导入节点。

    保留旧接口。
    """

    query = f"""
    LOAD CSV WITH HEADERS
    FROM "file:///" + $source_file AS row

    CALL (row) {{
        MERGE (
            n:$($label) {{
                `{unique_column_name}`:
                row[$unique_column_name]
            }}
        )

        FOREACH (
            k IN $properties |
            SET n[k] = row[k]
        )
    }}
    IN TRANSACTIONS OF 1000 ROWS
    """

    return graphdb.send_query(
        query,
        {
            "source_file": source_file,
            "label": label,
            "unique_column_name": unique_column_name,
            "properties": properties,
        },
    )


def import_nodes(
    node_construction: dict,
) -> dict:
    """导入一个节点构建规则。

    保留旧接口。
    """

    result = create_uniqueness_constraint(
        node_construction["label"],
        node_construction[
            "unique_column_name"
        ],
    )

    if result["status"] == "error":
        return result

    return load_nodes_from_csv(
        node_construction["source_file"],
        node_construction["label"],
        node_construction[
            "unique_column_name"
        ],
        node_construction["properties"],
    )


def import_relationships(
    rel: dict,
) -> Dict[str, Any]:
    """导入一个关系构建规则。

    保留旧接口。
    """

    query = f"""
    LOAD CSV WITH HEADERS
    FROM "file:///" + $source_file AS row

    CALL (row) {{
        MATCH (
            from_node:$($from_node_label) {{
                `{rel["from_node_column"]}`:
                row[$from_node_column]
            }}
        ),
        (
            to_node:$($to_node_label) {{
                `{rel["to_node_column"]}`:
                row[$to_node_column]
            }}
        )

        MERGE (
            from_node
        )-[r:$($relationship_type)]->(
            to_node
        )

        FOREACH (
            k IN $properties |
            SET r[k] = row[k]
        )
    }}
    IN TRANSACTIONS OF 1000 ROWS
    """

    return graphdb.send_query(
        query,
        {
            "source_file": rel["source_file"],
            "from_node_label": rel[
                "from_node_label"
            ],
            "from_node_column": rel[
                "from_node_column"
            ],
            "to_node_label": rel[
                "to_node_label"
            ],
            "to_node_column": rel[
                "to_node_column"
            ],
            "relationship_type": rel[
                "relationship_type"
            ],
            "properties": rel.get(
                "properties"
            ) or [],
        },
    )


def construct_domain_graph(
    construction_plan: dict,
) -> Dict[str, Any]:
    """根据构建计划导入节点和关系。

    Phase 4 开始：
        construct_domain_graph()
            ↓
        IngestionEngine.ingest()

    这样旧 API 不变，但底层实现升级。
    """

    engine = IngestionEngine()

    return engine.ingest(
        construction_plan
    )


__all__ = [
    "create_uniqueness_constraint",
    "load_nodes_from_csv",
    "import_nodes",
    "import_relationships",
    "construct_domain_graph",
]