from kg_builder.core.entity_resolution_engine import EntityResolutionConfig, EntityResolutionEngine


def main():
    engine = EntityResolutionEngine(neo4j_client=object(), config=EntityResolutionConfig(threshold=0.8, review_threshold=0.6))
    subjects = [
        {"id": "s1", "name": "Stockholm Chair", "color": "black"},
        {"id": "s2", "name": "Malmö Desk", "color": "white"},
    ]
    domains = [
        {"id": "d1", "name": "stockholm chair", "color": "black"},
        {"id": "d2", "name": "malmo desk", "color": "white"},
    ]
    report = engine.resolve_records(subjects, domains, "name", "name", blocking_key="name", attribute_pairs=[("color", "color")])
    assert report["candidate_count"] == 2
    assert report["matched_count"] == 2
    metrics = engine.evaluate(report["decisions"], [("s1", "d1"), ("s2", "d2")])
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["f1"] == 1.0
    print("🎉 Level 20 Entity Resolution 2.0 全部通过")


if __name__ == "__main__":
    main()
