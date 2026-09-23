from kg_builder.core.evaluation import precision_recall_f1, retrieval_recall, answer_correctness, threshold_sweep


def main():
    metrics = precision_recall_f1({1, 2, 3}, {2, 3, 4})
    assert abs(metrics["precision"] - (2 / 3)) < 1e-5
    assert abs(metrics["recall"] - (2 / 3)) < 1e-5
    assert round(metrics["f1"], 6) == round(2 / 3, 6)
    assert retrieval_recall([1, 2], [2, 3]) == 0.5
    assert answer_correctness("a b c", "a b") == 1.0
    rows = threshold_sweep(
        [
            {"subject_id": "s1", "domain_id": "d1", "score": 0.95},
            {"subject_id": "s2", "domain_id": "d2", "score": 0.70},
        ],
        [("s1", "d1")],
        [0.5, 0.9],
    )
    assert rows[0]["recall"] == 1.0
    assert rows[1]["precision"] == 1.0
    print("🎉 Level 21 Evaluation Framework 全部通过")


if __name__ == "__main__":
    main()
