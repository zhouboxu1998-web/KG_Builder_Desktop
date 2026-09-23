from kg_builder.core.hybrid_retriever import HybridRetriever


def main():
    class FakeQueryEngine:
        def query(self, cypher, parameters=None):
            return {"status": "success", "result": [{"id": 1}]}
    retriever = HybridRetriever(neo4j_client=object(), query_engine=FakeQueryEngine())
    graph = {"status": "success", "result": [{"id": 1}, {"id": 2}]}
    vector = {"status": "success", "result": [{"id": 3}]}
    fused = retriever.fuse(graph, vector)
    assert fused["graph_count"] == 2
    assert fused["vector_count"] == 1
    assert len(fused["results"]) == 3
    skipped = retriever.vector_retrieve("", [0.1, 0.2])
    assert skipped["status"] == "skipped"
    print("🎉 Level 22 Hybrid Retrieval 全部通过")


if __name__ == "__main__":
    main()
