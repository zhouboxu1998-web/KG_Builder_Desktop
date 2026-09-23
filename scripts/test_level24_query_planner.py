from kg_builder.core.query_planner import QueryPlanner


class FakeGraphDB:
    def send_query(self, cypher, parameters=None):
        if "db.labels" in cypher:
            return {"status": "success", "query_result": [{"labels": ["Product", "Supplier"]}]}
        return {"status": "success", "query_result": [{"relationship_types": ["SUPPLIED_BY", "REVIEWS"]}]}


def main():
    planner = QueryPlanner(FakeGraphDB())
    schema = planner.inspect_schema()
    assert schema["labels"] == ["Product", "Supplier"]
    assert schema["relationship_types"] == ["SUPPLIED_BY", "REVIEWS"]
    linked = planner.link_entity("Stockholm Chair", ["Stockholm Chair", "Malmö Desk"])
    assert linked[0]["candidate"] == "Stockholm Chair"
    plan = planner.plan("哪些供应商提供椅子？")
    assert plan["status"] == "success"
    assert "generate_parameterized_cypher" in plan["steps"]
    print("🎉 Level 24 Query Planner 全部通过")


if __name__ == "__main__":
    main()
