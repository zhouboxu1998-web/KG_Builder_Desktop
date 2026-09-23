"""Query Planning / Entity Linking 的轻量确定性层。

它不替代 LLM，而是为 Query Agent 提供可验证的 schema 上下文和实体候选。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from rapidfuzz import process, fuzz

if TYPE_CHECKING:
    from kg_builder.core.neo4j_client import Neo4jClient


class QueryPlanner:
    def __init__(self, neo4j_client: Optional[Neo4jClient] = None):
        if neo4j_client is None:
            from kg_builder.core.neo4j_client import graphdb
            self.graphdb = graphdb
        else:
            self.graphdb = neo4j_client

    def inspect_schema(self) -> Dict[str, Any]:
        labels = self.graphdb.send_query(
            "CALL db.labels() YIELD label RETURN collect(label) AS labels"
        )
        rels = self.graphdb.send_query(
            "CALL db.relationshipTypes() YIELD relationshipType RETURN collect(relationshipType) AS relationship_types"
        )
        return {
            "labels": (labels.get("query_result") or [{}])[0].get("labels", []),
            "relationship_types": (rels.get("query_result") or [{}])[0].get("relationship_types", []),
        }

    @staticmethod
    def link_entity(
        text: str,
        candidates: List[str],
        limit: int = 5,
        score_cutoff: float = 55.0,
    ) -> List[Dict[str, Any]]:
        matches = process.extract(
            text,
            candidates,
            scorer=fuzz.WRatio,
            limit=limit,
            score_cutoff=score_cutoff,
        )
        return [
            {"candidate": value, "score": round(score / 100.0, 6)}
            for value, score, _ in matches
        ]

    def plan(self, question: str) -> Dict[str, Any]:
        schema = self.inspect_schema()
        return {
            "status": "success",
            "question": question,
            "schema": schema,
            "steps": [
                "identify_entities",
                "select_graph_pattern",
                "generate_parameterized_cypher",
                "validate_read_only_cypher",
                "retrieve",
                "compose_answer",
            ],
        }


__all__ = ["QueryPlanner"]
