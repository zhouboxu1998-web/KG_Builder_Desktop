"""轻量 Evaluation Framework：支持分类任务、Entity Resolution 与检索结果评估。"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Sequence, Set, Tuple


def precision_recall_f1(predicted: Iterable[Any], gold: Iterable[Any]) -> Dict[str, float | int]:
    predicted_set = set(predicted)
    gold_set = set(gold)
    tp = len(predicted_set & gold_set)
    fp = len(predicted_set - gold_set)
    fn = len(gold_set - predicted_set)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def retrieval_recall(retrieved: Sequence[Any], relevant: Iterable[Any]) -> float:
    relevant_set: Set[Any] = set(relevant)
    if not relevant_set:
        return 0.0
    return round(len(set(retrieved) & relevant_set) / len(relevant_set), 6)


def answer_correctness(answer: str, reference: str) -> float:
    """用于离线基线的简单 token overlap 指标；不是 LLM judge。"""
    a = {token for token in answer.lower().split() if token}
    b = {token for token in reference.lower().split() if token}
    if not b:
        return 0.0
    return round(len(a & b) / len(b), 6)


def threshold_sweep(
    decisions: Sequence[Dict[str, Any]],
    gold_pairs: Iterable[Tuple[str, str]],
    thresholds: Sequence[float],
) -> list[Dict[str, Any]]:
    gold = {(str(a), str(b)) for a, b in gold_pairs}
    rows = []
    for threshold in thresholds:
        predicted = {
            (str(item["subject_id"]), str(item["domain_id"]))
            for item in decisions
            if float(item.get("score", 0.0)) >= threshold
        }
        metrics = precision_recall_f1(predicted, gold)
        rows.append({"threshold": threshold, **metrics})
    return rows


__all__ = [
    "precision_recall_f1",
    "retrieval_recall",
    "answer_correctness",
    "threshold_sweep",
]
