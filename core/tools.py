from pathlib import Path
from itertools import islice
from typing import Dict, Any

from google.adk.tools import ToolContext
from core.neo4j_client import graphdb, tool_success, tool_error
from core.helper import get_neo4j_import_dir


def get_approved_user_goal(tool_context: ToolContext):
    """返回用户的目标，这是一个包含图（Graph）的类型及其描述的字典。"""
    if "approved_user_goal" not in tool_context.state:
        return tool_error("未设置 approved_user_goal。请要求用户明确其目标（图的类型和描述）。")
    return tool_success("approved_user_goal", tool_context.state["approved_user_goal"])


def get_approved_files(tool_context: ToolContext):
    """返回已获批用于导入的文件。"""
    if "approved_files" not in tool_context.state:
        return tool_error("未设置 approved_files。请要求用户批准推荐的文件。")
    return tool_success("approved_files", tool_context.state["approved_files"])


def sample_file(file_path: str) -> dict:
    """对文件进行采样，将其内容作为文本读取（最多读取 100 行）。"""
    import_dir = Path(get_neo4j_import_dir() or "")

    if not import_dir.exists():
        return tool_error(f"NEO4J_IMPORT_DIR 不存在或未定义: {import_dir}")

    full_path_to_file = import_dir / file_path

    if not full_path_to_file.exists():
        return tool_error(f"导入目录中不存在该文件: {file_path}")

    try:
        with open(full_path_to_file, 'r', encoding='utf-8') as file:
            lines = list(islice(file, 100))
            content = ''.join(lines)
            return tool_success("content", content)
    except Exception as e:
        return tool_error(f"读取或处理文件 {file_path} 时出错: {e}")


# ==========================================
# Neo4j 数据库运维与图谱构建工具集
# ==========================================

def neo4j_is_ready():
    return graphdb.send_query("RETURN 'Neo4j is Ready!' as message")


def drop_neo4j_indexes() -> Dict[str, Any]:
    """删除 neo4j 图数据库中现有的所有约束和索引"""
    list_constraints = graphdb.send_query("SHOW CONSTRAINTS YIELD name")
    if list_constraints.get("status") == "error":
        return list_constraints

    for row in list_constraints.get("query_result", []):
        res = graphdb.send_query("DROP CONSTRAINT $name", {"name": row["name"]})
        if res.get("status") == "error": return res

    list_indexes = graphdb.send_query("SHOW INDEXES YIELD name")
    if list_indexes.get("status") == "error":
        return list_indexes

    for row in list_indexes.get("query_result", []):
        res = graphdb.send_query("DROP INDEX $name", {"name": row["name"]})
        if res.get("status") == "error": return res

    return tool_success("message", "Neo4j 的约束和索引已删除。")


def clear_neo4j_data() -> Dict[str, Any]:
    """清除 neo4j 图数据库中的所有数据 (慎用)"""
    res = graphdb.send_query("MATCH (n) CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS")
    if res.get("status") == "error":
        return res
    return tool_success("message", "Neo4j 图数据库已重置。")


def create_uniqueness_constraint(label: str, unique_property_key: str) -> Dict[str, Any]:
    """为节点创建唯一性约束"""
    constraint_name = f"{label}_{unique_property_key}_constraint"
    query = f"""CREATE CONSTRAINT `{constraint_name}` IF NOT EXISTS
    FOR (n:`{label}`) REQUIRE n.`{unique_property_key}` IS UNIQUE"""
    return graphdb.send_query(query)


def load_nodes_from_csv(source_file: str, label: str, unique_column_name: str, properties: list[str]) -> Dict[str, Any]:
    """从 CSV 文件批量加载节点"""
    query = f"""LOAD CSV WITH HEADERS FROM "file:///" + $source_file AS row
    CALL (row) {{
        MERGE (n:$($label) {{ {unique_column_name} : row[$unique_column_name] }})
        FOREACH (k IN $properties | SET n[k] = row[k])
    }} IN TRANSACTIONS OF 1000 ROWS
    """
    return graphdb.send_query(query, {
        "source_file": source_file,
        "label": label,
        "unique_column_name": unique_column_name,
        "properties": properties
    })