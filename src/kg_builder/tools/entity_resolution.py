"""Entity Resolution 2.0 的兼容工具层。

保留原有公开函数，内部统一委托给 EntityResolutionEngine。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from rapidfuzz import fuzz

from kg_builder.core.entity_resolution_engine import (
    EntityResolutionConfig,
    EntityResolutionEngine,
    normalize_text,
)
from kg_builder.core.errors import EntityResolutionError
from kg_builder.core.neo4j_client import graphdb


def _all_labels() -> List[str]:
    result = graphdb.send_query(
        "CALL db.labels() YIELD label RETURN collect(label) AS labels"
    )
    if result.get("status") == "error":
        return []
    return (result.get("query_result") or [{}])[0].get("labels") or []


def has_subject_graph() -> bool:
    return "__Entity__" in _all_labels()


def find_unique_entity_labels() -> List[str]:
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
    if result.get("status") == "error":
        return []
    return (result.get("query_result") or [{}])[0].get("unique_entity_labels") or []


def find_unique_domain_keys(domain_label: str) -> List[str]:
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
    if result.get("status") == "error":
        return []
    return (result.get("query_result") or [{}])[0].get("unique_domain_keys") or []


def find_unique_entity_keys(entity_label: str) -> List[str]:
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
    if result.get("status") == "error":
        return []
    return (result.get("query_result") or [{}])[0].get("unique_entity_keys") or []


def normalize_key(label: str, key: str) -> str:
    lowered = key.lower()
    unprefixed = re.sub(rf"^{label.lower()}[_ ]*", "", lowered)
    return re.sub(r"\s+", "_", unprefixed)


def correlate_entity_and_domain_keys(
    label: str,
    entity_keys: List[str],
    domain_keys: List[str],
    similarity: float = 0.9,
) -> List[Tuple[str, str, float]]:
    correlated = []
    for entity_key in entity_keys:
        for domain_key in domain_keys:
            score = fuzz.ratio(
                normalize_key(label, entity_key),
                normalize_key(label, domain_key),
            ) / 100.0
            if score >= similarity:
                correlated.append((entity_key, domain_key, score))
    correlated.sort(key=lambda x: x[2], reverse=True)
    return correlated


def correlate_subject_and_domain_nodes(
    label: str,
    entity_key: str,
    domain_key: str,
    similarity: float = 0.9,
) -> dict:
    engine = EntityResolutionEngine(
        neo4j_client=graphdb,
        config=EntityResolutionConfig(threshold=similarity, review_threshold=max(0.0, similarity - 0.15)),
    )
    result = graphdb.send_query(
        """
        MATCH (entity:$($entityLabel):`__Entity__`),
              (domain:$($entityLabel))
        WHERE NOT domain:`__Entity__`
          AND entity[$entityKey] IS NOT NULL
          AND domain[$domainKey] IS NOT NULL
          AND apoc.text.jaroWinklerDistance(
              toString(entity[$entityKey]),
              toString(domain[$domainKey])
          ) < $distance
        MERGE (entity)-[r:CORRESPONDS_TO]->(domain)
        ON CREATE SET r.created_at = datetime(), r.score = $similarity
        ON MATCH SET r.updated_at = datetime(), r.score = $similarity
        RETURN $entityLabel AS entityLabel, count(r) AS relationshipCount
        """,
        {
            "entityLabel": label,
            "entityKey": entity_key,
            "domainKey": domain_key,
            "distance": 1.0 - similarity,
            "similarity": similarity,
        },
    )
    if result.get("status") == "error":
        raise EntityResolutionError(
            result.get("error_message", "实体关系写入失败。"),
            details={"label": label, "entity_key": entity_key, "domain_key": domain_key},
        )
    return result


def _load_nodes_for_label(label: str) -> tuple[list[dict], list[dict]]:
    result = graphdb.send_query(
        """
        MATCH (n:$($label))
        RETURN elementId(n) AS id, properties(n) AS properties,
               n:`__Entity__` AS is_entity
        """,
        {"label": label},
    )
    if result.get("status") == "error":
        raise EntityResolutionError(
            result.get("error_message", "读取实体解析节点失败。"),
            details={"label": label},
        )
    subjects, domains = [], []
    for row in result.get("query_result") or []:
        record = dict(row.get("properties") or {})
        record["id"] = str(row.get("id"))
        if row.get("is_entity"):
            subjects.append(record)
        else:
            domains.append(record)
    return subjects, domains


def _select_key_pair(label: str, entity_keys: list[str], domain_keys: list[str], threshold: float) -> tuple[str, str, float] | None:
    pairs = correlate_entity_and_domain_keys(label, entity_keys, domain_keys, similarity=threshold)
    return pairs[0] if pairs else None


def run_entity_resolution(
    similarity: float = 0.8,
    review_threshold: float | None = None,
) -> List[dict]:
    """运行 Entity Resolution 2.0：候选生成 → Blocking → 相似度 → Score → Threshold → CORRESPONDS_TO。"""
    labels = find_unique_entity_labels()
    if not labels:
        return [{
            "label": "(无)",
            "matched": False,
            "error": "数据库中没有 __Entity__ 标签的节点。请先执行 'build-unstr'。",
        }]

    threshold = similarity
    review = review_threshold if review_threshold is not None else max(0.0, threshold - 0.15)
    engine = EntityResolutionEngine(
        neo4j_client=graphdb,
        config=EntityResolutionConfig(threshold=threshold, review_threshold=review),
    )

    results: List[dict] = []
    for label in labels:
        entry: Dict[str, Any] = {"label": label, "matched": False, "decision": "none"}
        try:
            entity_keys = find_unique_entity_keys(label)
            domain_keys = find_unique_domain_keys(label)
            selected = _select_key_pair(label, entity_keys, domain_keys, threshold)
            if selected is None:
                entry["decision"] = "reject"
                results.append(entry)
                continue

            entity_key, domain_key, key_score = selected
            subjects, domains = _load_nodes_for_label(label)
            attribute_pairs = [
                (left, right)
                for left, right, _ in correlate_entity_and_domain_keys(
                    label, entity_keys, domain_keys, similarity=max(0.7, threshold - 0.15)
                )
                if (left, right) != (entity_key, domain_key)
            ][:5]
            report = engine.resolve_records(
                subjects,
                domains,
                subject_name_key=entity_key,
                domain_name_key=domain_key,
                blocking_key=entity_key,
                domain_blocking_key=domain_key,
                attribute_pairs=attribute_pairs,
            )
            write_result = engine.write_matches_to_graph(
                label=label,
                subject_key=entity_key,
                domain_key=domain_key,
                decisions=report["decisions"],
            )
            entry.update({
                "matched": report["matched_count"] > 0,
                "decision": "match" if report["matched_count"] > 0 else "review",
                "entity_key": entity_key,
                "domain_key": domain_key,
                "similarity": key_score,
                "threshold": threshold,
                "review_threshold": review,
                "candidate_count": report["candidate_count"],
                "matched_count": report["matched_count"],
                "review_count": report["review_count"],
                "rejected_count": report["rejected_count"],
                "relationship_count": write_result["created_count"],
            })
        except Exception as error:
            entry["decision"] = "error"
            entry["error"] = str(error)
        results.append(entry)
    return results


__all__ = [
    "has_subject_graph",
    "find_unique_entity_labels",
    "find_unique_domain_keys",
    "find_unique_entity_keys",
    "normalize_key",
    "correlate_entity_and_domain_keys",
    "correlate_subject_and_domain_nodes",
    "run_entity_resolution",
]
