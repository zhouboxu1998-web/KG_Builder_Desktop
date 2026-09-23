"""Hybrid GraphRAG 检索器。

Graph retrieval 是必选能力；Vector retrieval 为可选能力。
当 Neo4j Vector Index 未配置或 embedding 不可用时，vector 分支优雅降级，
因此本模块不会阻塞现有图查询系统。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

if TYPE_CHECKING:
    from kg_builder.core.neo4j_client import Neo4jClient
    from kg_builder.core.query_engine import QueryEngine


class HybridRetriever:
    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        query_engine: Optional[QueryEngine] = None,
    ):
        if neo4j_client is None and query_engine is None:
            from kg_builder.core.neo4j_client import graphdb
            neo4j_client = graphdb
        self.graphdb = neo4j_client
        if query_engine is not None:
            self.query_engine = query_engine
        else:
            from kg_builder.core.query_engine import QueryEngine
            self.query_engine = QueryEngine(neo4j_client=self.graphdb)

    def graph_retrieve(
        self,
        cypher: str,
        parameters: Optional[dict] = None,
    ) -> Dict[str, Any]:
        return self.query_engine.query(cypher, parameters=parameters)

    def vector_retrieve(
        self,
        index_name: str,
        embedding: List[float],
        top_k: int = 5,
        score_threshold: float = 0.0,
    ) -> Dict[str, Any]:
        if not index_name:
            return {
                "status": "skipped",
                "result": [],
                "result_count": 0,
                "error_message": "未配置 Neo4j Vector Index。",
            }
        query = """
        CALL db.index.vector.queryNodes($index_name, $top_k, $embedding)
        YIELD node, score
        WHERE score >= $score_threshold
        RETURN node, score
        ORDER BY score DESC
        """
        result = self.graphdb.send_query(
            query,
            {
                "index_name": index_name,
                "top_k": top_k,
                "embedding": embedding,
                "score_threshold": score_threshold,
            },
        )
        if result.get("status") == "error":
            return {
                "status": "skipped",
                "result": [],
                "result_count": 0,
                "error_message": result.get("error_message"),
            }
        rows = result.get("query_result") or []
        return {
            "status": "success",
            "result": rows,
            "result_count": len(rows),
            "error_message": None,
        }

    @staticmethod
    def fuse(
        graph_result: Dict[str, Any],
        vector_result: Optional[Dict[str, Any]] = None,
        graph_weight: float = 0.6,
        vector_weight: float = 0.4,
    ) -> Dict[str, Any]:
        vector_result = vector_result or {"result": []}
        graph_rows = list(graph_result.get("result") or graph_result.get("query_result") or [])
        vector_rows = list(vector_result.get("result") or [])
        return {
            "status": "success",
            "graph_count": len(graph_rows),
            "vector_count": len(vector_rows),
            "graph_weight": graph_weight,
            "vector_weight": vector_weight,
            "graph_results": graph_rows,
            "vector_results": vector_rows,
            "results": graph_rows + vector_rows,
        }

    def hybrid_retrieve(
        self,
        cypher: str,
        parameters: Optional[dict] = None,
        *,
        index_name: Optional[str] = None,
        embedding: Optional[List[float]] = None,
        top_k: int = 5,
        embedder: Optional[Callable[[str], List[float]]] = None,
        query_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        graph_result = self.graph_retrieve(cypher, parameters)
        if graph_result.get("status") != "success":
            return graph_result

        vector_result = {"status": "skipped", "result": []}
        if index_name and embedding is None and embedder and query_text:
            embedding = embedder(query_text)
        if index_name and embedding is not None:
            vector_result = self.vector_retrieve(index_name, embedding, top_k=top_k)
        fused = self.fuse(graph_result, vector_result)
        fused["query"] = cypher
        fused["parameters"] = parameters or {}
        return fused


__all__ = ["HybridRetriever"]
