"""Entity Resolution 2.0 核心引擎。

提供纯 Python 的候选生成、阻塞、特征计算、评分、阈值决策与评估，
并可通过 Neo4j Client 将高置信匹配写回 CORRESPONDS_TO。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Sequence, Tuple

from rapidfuzz.distance import JaroWinkler
from rapidfuzz import fuzz

from kg_builder.core.errors import EntityResolutionError

if TYPE_CHECKING:
    from kg_builder.core.neo4j_client import Neo4jClient


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def jaro_winkler(a: Any, b: Any) -> float:
    x, y = normalize_text(a), normalize_text(b)
    if not x or not y:
        return 0.0
    return float(JaroWinkler.normalized_similarity(x, y))


@dataclass(frozen=True)
class ResolutionDecision:
    subject_id: str
    domain_id: str
    score: float
    decision: str
    features: Dict[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EntityResolutionConfig:
    threshold: float = 0.90
    review_threshold: float = 0.75
    name_weight: float = 0.65
    attribute_weight: float = 0.35
    blocking_prefix_length: int = 3

    def validate(self) -> None:
        if not 0 <= self.review_threshold <= 1:
            raise EntityResolutionError("review_threshold 必须在 [0, 1]。")
        if not 0 <= self.threshold <= 1:
            raise EntityResolutionError("threshold 必须在 [0, 1]。")
        if self.review_threshold > self.threshold:
            raise EntityResolutionError("review_threshold 不能高于 threshold。")
        if self.name_weight < 0 or self.attribute_weight < 0:
            raise EntityResolutionError("权重不能为负数。")
        if self.name_weight + self.attribute_weight <= 0:
            raise EntityResolutionError("至少一个评分权重必须大于 0。")
        if self.blocking_prefix_length < 1:
            raise EntityResolutionError("blocking_prefix_length 必须大于 0。")


class EntityResolutionEngine:
    """实现 Entity Resolution 2.0。"""

    def __init__(self, neo4j_client: Optional[Neo4jClient] = None, config: Optional[EntityResolutionConfig] = None):
        self.graphdb = neo4j_client
        self.config = config or EntityResolutionConfig()
        self.config.validate()
        self.last_report: Dict[str, Any] = {}

    @staticmethod
    def make_block_key(value: Any, prefix_length: int = 3) -> str:
        normalized = normalize_text(value)
        return normalized[:prefix_length] if normalized else ""

    def generate_candidates(
        self,
        subject_records: Sequence[Dict[str, Any]],
        domain_records: Sequence[Dict[str, Any]],
        blocking_key: str,
    ) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
        buckets: Dict[str, List[Dict[str, Any]]] = {}
        for record in domain_records:
            key = self.make_block_key(record.get(blocking_key), self.config.blocking_prefix_length)
            if key:
                buckets.setdefault(key, []).append(record)

        candidates: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        for subject in subject_records:
            key = self.make_block_key(subject.get(blocking_key), self.config.blocking_prefix_length)
            if not key:
                continue
            for domain in buckets.get(key, []):
                candidates.append((subject, domain))
        return candidates

    def score_pair(
        self,
        subject: Dict[str, Any],
        domain: Dict[str, Any],
        subject_name_key: str,
        domain_name_key: str,
        attribute_pairs: Optional[Sequence[Tuple[str, str]]] = None,
    ) -> ResolutionDecision:
        features: Dict[str, float] = {}
        name_score = jaro_winkler(subject.get(subject_name_key), domain.get(domain_name_key))
        features["name_similarity"] = name_score

        attribute_scores: List[float] = []
        for subject_key, domain_key in attribute_pairs or []:
            left = normalize_text(subject.get(subject_key))
            right = normalize_text(domain.get(domain_key))
            if left and right:
                attribute_scores.append(jaro_winkler(left, right))

        attribute_score = sum(attribute_scores) / len(attribute_scores) if attribute_scores else 0.0
        features["attribute_similarity"] = attribute_score

        if attribute_scores:
            total_weight = self.config.name_weight + self.config.attribute_weight
            score = (
                self.config.name_weight * name_score
                + self.config.attribute_weight * attribute_score
            ) / total_weight
        else:
            score = name_score

        if score >= self.config.threshold:
            decision = "match"
        elif score >= self.config.review_threshold:
            decision = "review"
        else:
            decision = "reject"

        return ResolutionDecision(
            subject_id=str(subject.get("id", subject.get(subject_name_key, ""))),
            domain_id=str(domain.get("id", domain.get(domain_name_key, ""))),
            score=round(score, 6),
            decision=decision,
            features=features,
        )

    def resolve_records(
        self,
        subject_records: Sequence[Dict[str, Any]],
        domain_records: Sequence[Dict[str, Any]],
        subject_name_key: str,
        domain_name_key: str,
        blocking_key: Optional[str] = None,
        attribute_pairs: Optional[Sequence[Tuple[str, str]]] = None,
        domain_blocking_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not subject_name_key or not domain_name_key:
            raise EntityResolutionError("subject_name_key 和 domain_name_key 不能为空。")

        if blocking_key:
            if domain_blocking_key:
                buckets: Dict[str, List[Dict[str, Any]]] = {}
                for record in domain_records:
                    key = self.make_block_key(record.get(domain_blocking_key), self.config.blocking_prefix_length)
                    if key:
                        buckets.setdefault(key, []).append(record)
                candidates = []
                for subject in subject_records:
                    key = self.make_block_key(subject.get(blocking_key), self.config.blocking_prefix_length)
                    candidates.extend((subject, domain) for domain in buckets.get(key, []))
            else:
                candidates = self.generate_candidates(subject_records, domain_records, blocking_key)
        else:
            candidates = [(s, d) for s in subject_records for d in domain_records]

        best_by_subject: Dict[str, ResolutionDecision] = {}
        for subject, domain in candidates:
            decision = self.score_pair(
                subject, domain,
                subject_name_key, domain_name_key,
                attribute_pairs=attribute_pairs,
            )
            current = best_by_subject.get(decision.subject_id)
            if current is None or decision.score > current.score:
                best_by_subject[decision.subject_id] = decision

        decisions = list(best_by_subject.values())
        matches = [d.to_dict() for d in decisions if d.decision == "match"]
        reviews = [d.to_dict() for d in decisions if d.decision == "review"]
        rejects = [d.to_dict() for d in decisions if d.decision == "reject"]
        report = {
            "status": "success",
            "subject_count": len(subject_records),
            "domain_count": len(domain_records),
            "candidate_count": len(candidates),
            "matched_count": len(matches),
            "review_count": len(reviews),
            "rejected_count": len(rejects),
            "decisions": [d.to_dict() for d in decisions],
            "config": asdict(self.config),
        }
        self.last_report = report
        return report

    @staticmethod
    def evaluate(
        decisions: Iterable[Dict[str, Any] | ResolutionDecision],
        gold_pairs: Iterable[Tuple[str, str]],
    ) -> Dict[str, Any]:
        gold = {(str(a), str(b)) for a, b in gold_pairs}
        predicted = set()
        for item in decisions:
            record = item.to_dict() if isinstance(item, ResolutionDecision) else item
            if record.get("decision") == "match":
                predicted.add((str(record.get("subject_id")), str(record.get("domain_id"))))
        tp = len(predicted & gold)
        fp = len(predicted - gold)
        fn = len(gold - predicted)
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

    def write_matches_to_graph(
        self,
        label: str,
        subject_key: str,
        domain_key: str,
        decisions: Sequence[Dict[str, Any] | ResolutionDecision],
    ) -> Dict[str, Any]:
        if self.graphdb is None:
            raise EntityResolutionError("write_matches_to_graph 需要注入 Neo4jClient。")
        matched = []
        for item in decisions:
            record = item.to_dict() if isinstance(item, ResolutionDecision) else item
            if record.get("decision") == "match":
                matched.append(record)
        if not matched:
            return {"status": "success", "created_count": 0, "decisions": []}

        query = """
        MATCH (entity:$($label):`__Entity__`), (domain:$($label))
        WHERE NOT domain:`__Entity__`
          AND elementId(entity) = $subjectId
          AND elementId(domain) = $domainId
        MERGE (entity)-[r:CORRESPONDS_TO]->(domain)
        ON CREATE SET r.created_at = datetime(), r.score = $score
        ON MATCH SET r.updated_at = datetime(), r.score = $score
        RETURN count(r) AS count
        """
        created = 0
        for record in matched:
            result = self.graphdb.send_query(
                query,
                {
                    "label": label,
                    "subjectKey": subject_key,
                    "domainKey": domain_key,
                    "subjectId": record["subject_id"],
                    "domainId": record["domain_id"],
                    "score": record["score"],
                },
            )
            if result.get("status") == "error":
                raise EntityResolutionError(
                    result.get("error_message", "写入 CORRESPONDS_TO 失败。"),
                    details={"label": label, "subject_id": record["subject_id"]},
                )
            created += int((result.get("query_result") or [{}])[0].get("count", 0))
        return {
            "status": "success",
            "created_count": created,
            "decisions": matched,
        }

    def get_report(self) -> Dict[str, Any]:
        return dict(self.last_report)


__all__ = [
    "EntityResolutionConfig",
    "EntityResolutionEngine",
    "ResolutionDecision",
    "normalize_text",
    "jaro_winkler",
]
