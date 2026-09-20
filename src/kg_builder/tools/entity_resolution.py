"""实体解析：把主题图（评论抽取）和领域图（BOM 导入）连接起来。

对应 knowledge_graph_construction_2.ipynb 中：
    - find_unique_entity_labels
    - find_unique_domain_keys
    - find_unique_entity_keys
    - normalize_key
    - correlate_entity_and_domain_keys
    - correlate_subject_and_domain_nodes
"""

import re
from typing import List, Tuple

from rapidfuzz import fuzz

from kg_builder.core.neo4j_client import graphdb


# ============================================================
# 查询辅助（带标签存在性检查，避免 5.x 报错）
# ============================================================

def _all_labels() -> List[str]:
    """列出数据库中所有标签。"""
    r = graphdb.send_query(
        "CALL db.labels() YIELD label RETURN collect(label) AS labels"
    )
    if r["status"] == "error":
        return []
    if not r["query_result"]:
        return []
    return r["query_result"][0]["labels"] or []


def has_subject_graph() -> bool:
    """检查数据库里是否已有主题图（__Entity__ 标签）。"""
    return "__Entity__" in _all_labels()


def find_unique_entity_labels() -> List[str]:
    """找出主题图中所有实体标签（排除 __ 开头的内部标签）。"""
    if not has_subject_graph():
        return []

    result = graphdb.send_query("""
        MATCH (n)
        WHERE n:`__Entity__`
        WITH DISTINCT labels(n) AS entity_labels
        UNWIND entity_labels AS entity_label
        WITH entity_label
        WHERE NOT entity_label STARTS WITH "__"
        RETURN collect(entity_label) AS unique_entity_labels
    """)
    if result["status"] == "error":
        return []
    if not result["query_result"]:
        return []
    return result["query_result"][0]["unique_entity_labels"] or []


def find_unique_domain_keys(domain_label: str) -> List[str]:
    """找出领域节点（非 __Entity__）的所有属性键。"""
    if domain_label not in _all_labels():
        return []

    result = graphdb.send_query(
        """
        MATCH (n:$($domainLabel))
        WHERE NOT n:`__Entity__`
        WITH DISTINCT keys(n) AS domainKeys
        UNWIND domainKeys AS domainKey
        RETURN collect(distinct(domainKey)) AS unique_domain_keys
        """,
        {"domainLabel": domain_label},
    )
    if result["status"] == "error":
        return []
    return result["query_result"][0]["unique_domain_keys"] or []


def find_unique_entity_keys(entity_label: str) -> List[str]:
    """找出实体节点（带 __Entity__）的所有属性键。"""
    labels = _all_labels()
    if "__Entity__" not in labels or entity_label not in labels:
        return []

    result = graphdb.send_query(
        """
        MATCH (n:$($entityLabel))
        WHERE n:`__Entity__`
        WITH DISTINCT keys(n) AS entityKeys
        UNWIND entityKeys AS entityKey
        RETURN collect(distinct(entityKey)) AS unique_entity_keys
        """,
        {"entityLabel": entity_label},
    )
    if result["status"] == "error":
        return []
    return result["query_result"][0]["unique_entity_keys"] or []


# ============================================================
# 键名归一化 + 相似度
# ============================================================

def normalize_key(label: str, key: str) -> str:
    """属性键归一化：去 label 前缀、小写、空格转下划线。"""
    lowered = key.lower()
    unprefixed = re.sub(rf"^{label.lower()}[_ ]*", "", lowered)
    return re.sub(r" ", "_", unprefixed)


def correlate_entity_and_domain_keys(
    label: str,
    entity_keys: List[str],
    domain_keys: List[str],
    similarity: float = 0.9,
) -> List[Tuple[str, str, float]]:
    """在实体属性键和领域属性键之间找相似对。"""
    correlated = []
    for ek in entity_keys:
        for dk in domain_keys:
            s = fuzz.ratio(
                normalize_key(label, ek),
                normalize_key(label, dk),
            ) / 100
            if s > similarity:
                correlated.append((ek, dk, s))
    correlated.sort(key=lambda x: x[2], reverse=True)
    return correlated


# ============================================================
# 建立 CORRESPONDS_TO 关系
# ============================================================

def correlate_subject_and_domain_nodes(
    label: str,
    entity_key: str,
    domain_key: str,
    similarity: float = 0.9,
) -> dict:
    """在实体节点和领域节点之间建立 CORRESPONDS_TO 关系。"""
    result = graphdb.send_query(
        """
        MATCH (entity:$($entityLabel):`__Entity__`),
              (domain:$($entityLabel))
        WHERE NOT domain:`__Entity__`
          AND apoc.text.jaroWinklerDistance(
              entity[$entityKey], domain[$domainKey]
          ) < $distance

        MERGE (entity)-[r:CORRESPONDS_TO]->(domain)
        ON CREATE SET r.created_at = datetime()
        ON MATCH  SET r.updated_at = datetime()

        RETURN $entityLabel AS entityLabel, count(r) AS relationshipCount
        """,
        {
            "entityLabel": label,
            "entityKey": entity_key,
            "domainKey": domain_key,
            "distance": (1.0 - similarity),
        },
    )
    if result["status"] == "error":
        raise Exception(result.get("error_message"))
    return result


# ============================================================
# 一键执行
# ============================================================

def run_entity_resolution(similarity: float = 0.8) -> List[dict]:
    """遍历所有实体标签，自动匹配属性键并建立 CORRESPONDS_TO 关系。"""
    labels = find_unique_entity_labels()

    if not labels:
        return [{
            "label": "(无)",
            "matched": False,
            "error": (
                "数据库中没有 __Entity__ 标签的节点。"
                "请先执行 'build-unstr'。"
            ),
        }]

    results = []
    for label in labels:
        entry = {"label": label, "matched": False}
        try:
            entity_keys = find_unique_entity_keys(label)
            domain_keys = find_unique_domain_keys(label)

            pairs = correlate_entity_and_domain_keys(
                label, entity_keys, domain_keys, similarity=similarity
            )
            if pairs:
                ek, dk, score = pairs[0]
                entry.update({
                    "matched": True,
                    "entity_key": ek,
                    "domain_key": dk,
                    "similarity": score,
                })
                correlate_subject_and_domain_nodes(
                    label, ek, dk, similarity=similarity
                )
        except Exception as e:
            entry["error"] = str(e)
        results.append(entry)
    return results