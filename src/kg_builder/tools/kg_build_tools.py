"""结构化图谱构建：从 CSV 导入节点与关系。"""
from typing import Any, Dict, List

from kg_builder.core.neo4j_client import graphdb, tool_error


def create_uniqueness_constraint(
    label: str, unique_property_key: str
) -> Dict[str, Any]:
    constraint_name = f"{label}_{unique_property_key}_constraint"
    query = f"""CREATE CONSTRAINT `{constraint_name}` IF NOT EXISTS
    FOR (n:`{label}`)
    REQUIRE n.`{unique_property_key}` IS UNIQUE"""
    return graphdb.send_query(query)


def load_nodes_from_csv(
    source_file: str,
    label: str,
    unique_column_name: str,
    properties: List[str],
) -> Dict[str, Any]:
    query = f"""LOAD CSV WITH HEADERS FROM "file:///" + $source_file AS row
    CALL (row) {{
        MERGE (n:$($label) {{ {unique_column_name} : row[$unique_column_name] }})
        FOREACH (k IN $properties | SET n[k] = row[k])
    }} IN TRANSACTIONS OF 1000 ROWS
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


def import_nodes(node_construction: dict) -> dict:
    r = create_uniqueness_constraint(
        node_construction["label"], node_construction["unique_column_name"]
    )
    if r["status"] == "error":
        return r
    return load_nodes_from_csv(
        node_construction["source_file"],
        node_construction["label"],
        node_construction["unique_column_name"],
        node_construction["properties"],
    )


def import_relationships(rel: dict) -> Dict[str, Any]:
    query = f"""LOAD CSV WITH HEADERS FROM "file:///" + $source_file AS row
    CALL (row) {{
        MATCH (from_node:$($from_node_label) {{ {rel['from_node_column']} : row[$from_node_column] }}),
              (to_node:$($to_node_label) {{ {rel['to_node_column']} : row[$to_node_column] }})
        MERGE (from_node)-[r:$($relationship_type)]->(to_node)
        FOREACH (k IN $properties | SET r[k] = row[k])
    }} IN TRANSACTIONS OF 1000 ROWS
    """
    return graphdb.send_query(
        query,
        {
            "source_file": rel["source_file"],
            "from_node_label": rel["from_node_label"],
            "from_node_column": rel["from_node_column"],
            "to_node_label": rel["to_node_label"],
            "to_node_column": rel["to_node_column"],
            "relationship_type": rel["relationship_type"],
            "properties": rel["properties"],
        },
    )


def construct_domain_graph(construction_plan: dict) -> Dict[str, Any]:
    """根据构建计划导入节点和关系。"""
    nodes = [v for v in construction_plan.values() if v.get("construction_type") == "node"]
    rels = [v for v in construction_plan.values() if v.get("construction_type") == "relationship"]

    for n in nodes:
        r = import_nodes(n)
        if r["status"] == "error":
            return r
    for rel in rels:
        r = import_relationships(rel)
        if r["status"] == "error":
            return r
    return {"status": "success"}