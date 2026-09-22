"""可靠的 Neo4j 图谱数据导入引擎。

Phase 4 负责：

    Schema
       ↓
    Validate
       ↓
    Normalize
       ↓
    Import
       ↓
    Verify
       ↓
    Statistics

设计原则：

1. SchemaEngine 负责 Schema 业务状态。
2. IngestionEngine 负责数据导入。
3. PipelineRuntime 不负责数据导入逻辑。
4. 所有操作尽量返回结构化结果，而不是直接抛异常。
5. 保留旧版 construct_domain_graph() 所需要的导入能力。
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from kg_builder.core.neo4j_client import graphdb


class IngestionEngine:
    """负责将已经批准的 Schema 数据导入 Neo4j。"""

    VALID_CONSTRUCTION_TYPES = {
        "node",
        "relationship",
    }

    def __init__(self, neo4j_client=None):
        self.graphdb = neo4j_client or graphdb

        self.status = "idle"

        self.report: Dict[str, Any] = {
            "status": "idle",
            "nodes": {},
            "relationships": {},
            "validation": {
                "valid": False,
                "errors": [],
                "warnings": [],
            },
            "statistics": {},
        }

    # ========================================================
    # Reset
    # ========================================================

    def reset(self) -> None:
        """重置本次导入状态。"""

        self.status = "idle"

        self.report = {
            "status": "idle",
            "nodes": {},
            "relationships": {},
            "validation": {
                "valid": False,
                "errors": [],
                "warnings": [],
            },
            "statistics": {},
        }

    # ========================================================
    # Schema Normalize
    # ========================================================

    def normalize_plan(self, plan: Optional[dict]) -> dict:
        """标准化 Schema 构建计划。

        不修改调用方传入的原始 plan。
        """

        if not plan:
            return {}

        normalized: Dict[str, Any] = {}

        for key, raw_rule in plan.items():
            if not isinstance(raw_rule, dict):
                continue

            rule = dict(raw_rule)

            construction_type = str(
                rule.get("construction_type", "")
            ).strip().lower()

            rule["construction_type"] = construction_type

            if "properties" not in rule or rule["properties"] is None:
                rule["properties"] = []

            if not isinstance(rule["properties"], list):
                rule["properties"] = list(rule["properties"])

            # 清理字符串字段
            string_fields = [
                "source_file",
                "label",
                "unique_column_name",
                "relationship_type",
                "from_node_label",
                "from_node_column",
                "to_node_label",
                "to_node_column",
            ]

            for field in string_fields:
                if isinstance(rule.get(field), str):
                    rule[field] = rule[field].strip()

            normalized_key = str(key).strip()

            if not normalized_key:
                normalized_key = (
                    rule.get("label")
                    or rule.get("relationship_type")
                    or ""
                )

            if normalized_key:
                normalized[normalized_key] = rule

        return normalized

    # ========================================================
    # File Validation
    # ========================================================

    def _resolve_source_file(self, source_file: str) -> Path:
        """解析 CSV 文件路径。

        支持：

        1. 绝对路径
        2. 当前工作目录下的路径
        3. config.IMPORT_DIR 下的文件
        """

        from kg_builder import config

        path = Path(source_file).expanduser()

        if path.is_absolute():
            return path

        candidates = [
            Path.cwd() / path,
            config.IMPORT_DIR / path,
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()

        # 即使不存在，也返回最可能的路径。
        return candidates[-1].resolve()

    def _read_csv_header(self, source_file: str) -> List[str]:
        """读取 CSV 表头。"""

        path = self._resolve_source_file(source_file)

        if not path.exists():
            raise FileNotFoundError(
                f"找不到 CSV 文件：{source_file}"
            )

        with path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as f:
            reader = csv.reader(f)
            header = next(reader, None)

        if not header:
            raise ValueError(
                f"CSV 文件为空或没有表头：{source_file}"
            )

        return [str(column).strip() for column in header]

    # ========================================================
    # CSV Inspection
    # ========================================================

    def inspect_csv(
        self,
        source_file: str,
        required_columns: Iterable[str],
    ) -> Dict[str, Any]:
        """检查 CSV 文件以及所需字段。"""

        required_columns = [
            str(column).strip()
            for column in required_columns
            if str(column).strip()
        ]

        result = {
            "source_file": source_file,
            "exists": False,
            "columns": [],
            "missing_columns": [],
            "valid": False,
        }

        try:
            path = self._resolve_source_file(source_file)

            if not path.exists():
                result["error"] = (
                    f"找不到 CSV 文件：{source_file}"
                )
                return result

            result["exists"] = True

            columns = self._read_csv_header(source_file)
            result["columns"] = columns

            missing = [
                column
                for column in required_columns
                if column not in columns
            ]

            result["missing_columns"] = missing
            result["valid"] = len(missing) == 0

            return result

        except Exception as e:
            result["error"] = str(e)
            return result

    # ========================================================
    # Node Validation
    # ========================================================

    def _validate_node_rule(
        self,
        key: str,
        rule: dict,
        errors: List[str],
        warnings: List[str],
    ) -> None:

        label = rule.get("label")
        unique_column = rule.get("unique_column_name")
        source_file = rule.get("source_file")

        if not label:
            errors.append(
                f"节点规则 {key} 缺少 label。"
            )

        if not unique_column:
            errors.append(
                f"节点规则 {key} 缺少 unique_column_name。"
            )

        if not source_file:
            errors.append(
                f"节点规则 {key} 缺少 source_file。"
            )
            return

        required_columns = [unique_column]

        properties = rule.get("properties") or []
        required_columns.extend(properties)

        inspection = self.inspect_csv(
            source_file,
            required_columns,
        )

        if not inspection["exists"]:
            errors.append(
                inspection.get(
                    "error",
                    f"无法读取文件 {source_file}",
                )
            )
            return

        missing = inspection.get(
            "missing_columns",
            [],
        )

        if missing:
            errors.append(
                f"{source_file} 缺少节点规则 "
                f"{key} 所需要的列：{missing}"
            )

        if unique_column in properties:
            warnings.append(
                f"节点 {label} 的唯一键 "
                f"{unique_column} 同时出现在 properties 中。"
            )

    # ========================================================
    # Relationship Validation
    # ========================================================

    def _validate_relationship_rule(
        self,
        key: str,
        rule: dict,
        node_labels: set,
        errors: List[str],
        warnings: List[str],
    ) -> None:

        relationship_type = rule.get("relationship_type")

        if not relationship_type:
            errors.append(
                f"关系规则 {key} 缺少 relationship_type。"
            )

        source_file = rule.get("source_file")

        if not source_file:
            errors.append(
                f"关系规则 {key} 缺少 source_file。"
            )
            return

        from_label = rule.get("from_node_label")
        from_column = rule.get("from_node_column")
        to_label = rule.get("to_node_label")
        to_column = rule.get("to_node_column")

        if not from_label:
            errors.append(
                f"关系规则 {key} 缺少 from_node_label。"
            )

        if not from_column:
            errors.append(
                f"关系规则 {key} 缺少 from_node_column。"
            )

        if not to_label:
            errors.append(
                f"关系规则 {key} 缺少 to_node_label。"
            )

        if not to_column:
            errors.append(
                f"关系规则 {key} 缺少 to_node_column。"
            )

        if from_label and from_label not in node_labels:
            errors.append(
                f"关系 {relationship_type} 引用了不存在的源节点："
                f"{from_label}"
            )

        if to_label and to_label not in node_labels:
            errors.append(
                f"关系 {relationship_type} 引用了不存在的目标节点："
                f"{to_label}"
            )

        required_columns = [
            column
            for column in (
                from_column,
                to_column,
            )
            if column
        ]

        properties = rule.get("properties") or []
        required_columns.extend(properties)

        inspection = self.inspect_csv(
            source_file,
            required_columns,
        )

        if not inspection["exists"]:
            errors.append(
                inspection.get(
                    "error",
                    f"无法读取文件 {source_file}",
                )
            )
            return

        missing = inspection.get(
            "missing_columns",
            [],
        )

        if missing:
            errors.append(
                f"{source_file} 缺少关系规则 "
                f"{key} 所需要的列：{missing}"
            )

    # ========================================================
    # Full Validation
    # ========================================================

    def validate_plan(
        self,
        plan: Optional[dict],
    ) -> Dict[str, Any]:
        """在真正访问 Neo4j 之前验证导入计划。"""

        normalized = self.normalize_plan(plan)

        errors: List[str] = []
        warnings: List[str] = []

        if not normalized:
            errors.append("导入计划为空。")

        node_rules = []
        relationship_rules = []

        for key, rule in normalized.items():
            construction_type = rule.get(
                "construction_type"
            )

            if construction_type not in self.VALID_CONSTRUCTION_TYPES:
                errors.append(
                    f"规则 {key} 的 "
                    f"construction_type 无效："
                    f"{construction_type}"
                )
                continue

            if construction_type == "node":
                node_rules.append((key, rule))

            elif construction_type == "relationship":
                relationship_rules.append((key, rule))

        node_labels = set()

        for key, rule in node_rules:
            label = rule.get("label")

            if label:
                if label in node_labels:
                    errors.append(
                        f"发现重复节点 label：{label}"
                    )
                node_labels.add(label)

            self._validate_node_rule(
                key,
                rule,
                errors,
                warnings,
            )

        relationship_types = set()

        for key, rule in relationship_rules:
            relationship_type = rule.get(
                "relationship_type"
            )

            if relationship_type:
                if relationship_type in relationship_types:
                    errors.append(
                        f"发现重复 relationship_type："
                        f"{relationship_type}"
                    )
                relationship_types.add(
                    relationship_type
                )

            self._validate_relationship_rule(
                key,
                rule,
                node_labels,
                errors,
                warnings,
            )

        result = {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "node_count": len(node_rules),
            "relationship_count": len(
                relationship_rules
            ),
        }

        self.report["validation"] = result

        if result["valid"]:
            self.status = "validated"
        else:
            self.status = "rejected"

        return result

    # ========================================================
    # Constraint
    # ========================================================

    def create_constraints(
        self,
        plan: dict,
    ) -> Dict[str, Any]:
        """为所有节点创建唯一约束。"""

        created = []
        errors = []

        for key, rule in plan.items():
            if rule.get("construction_type") != "node":
                continue

            label = rule["label"]
            unique_column = rule[
                "unique_column_name"
            ]

            constraint_name = (
                f"{label}_{unique_column}_constraint"
            )

            query = f"""
            CREATE CONSTRAINT `{constraint_name}`
            IF NOT EXISTS
            FOR (n:`{label}`)
            REQUIRE n.`{unique_column}` IS UNIQUE
            """

            result = self.graphdb.send_query(query)

            if result.get("status") == "error":
                errors.append(
                    {
                        "rule": key,
                        "error": result.get(
                            "error_message"
                        ),
                    }
                )
            else:
                created.append(
                    {
                        "rule": key,
                        "constraint": constraint_name,
                    }
                )

        return {
            "status": (
                "success"
                if not errors
                else "error"
            ),
            "created": created,
            "errors": errors,
        }

    # ========================================================
    # Node Import
    # ========================================================

    def import_node(
        self,
        rule: dict,
    ) -> Dict[str, Any]:
        """导入一个节点规则。"""

        source_file = rule["source_file"]
        label = rule["label"]
        unique_column = rule[
            "unique_column_name"
        ]
        properties = rule.get("properties") or []

        query = f"""
        LOAD CSV WITH HEADERS
        FROM "file:///" + $source_file AS row

        CALL (row) {{
            MERGE (
                n:$($label) {{
                    `{unique_column}`:
                    row[$unique_column_name]
                }}
            )

            FOREACH (
                k IN $properties |
                SET n[k] = row[k]
            )
        }}
        IN TRANSACTIONS OF 1000 ROWS
        """

        result = self.graphdb.send_query(
            query,
            {
                "source_file": source_file,
                "label": label,
                "unique_column_name": unique_column,
                "properties": properties,
            },
        )

        return result

    # ========================================================
    # Relationship Import
    # ========================================================

    def import_relationship(
        self,
        rule: dict,
    ) -> Dict[str, Any]:
        """导入一个关系规则。"""

        query = f"""
        LOAD CSV WITH HEADERS
        FROM "file:///" + $source_file AS row

        CALL (row) {{
            MATCH (
                from_node:$($from_node_label) {{
                    `{rule["from_node_column"]}`:
                    row[$from_node_column]
                }}
            ),
            (
                to_node:$($to_node_label) {{
                    `{rule["to_node_column"]}`:
                    row[$to_node_column]
                }}
            )

            MERGE (
                from_node
            )-[r:$($relationship_type)]->(
                to_node
            )

            FOREACH (
                k IN $properties |
                SET r[k] = row[k]
            )
        }}
        IN TRANSACTIONS OF 1000 ROWS
        """

        result = self.graphdb.send_query(
            query,
            {
                "source_file": rule["source_file"],
                "from_node_label": rule[
                    "from_node_label"
                ],
                "from_node_column": rule[
                    "from_node_column"
                ],
                "to_node_label": rule[
                    "to_node_label"
                ],
                "to_node_column": rule[
                    "to_node_column"
                ],
                "relationship_type": rule[
                    "relationship_type"
                ],
                "properties": rule.get(
                    "properties"
                ) or [],
            },
        )

        return result

    # ========================================================
    # Statistics
    # ========================================================

    def collect_statistics(
        self,
        plan: dict,
    ) -> Dict[str, Any]:
        """从 Neo4j 获取导入后的图谱统计信息。"""

        statistics: Dict[str, Any] = {
            "nodes": {},
            "relationships": {},
        }

        node_labels = {
            rule.get("label")
            for rule in plan.values()
            if rule.get("construction_type")
            == "node"
        }

        relationship_types = {
            rule.get("relationship_type")
            for rule in plan.values()
            if rule.get("construction_type")
            == "relationship"
        }

        for label in sorted(
            label for label in node_labels if label
        ):
            query = f"""
            MATCH (n:`{label}`)
            RETURN count(n) AS count
            """

            result = self.graphdb.send_query(query)

            if result.get("status") == "success":
                records = result.get(
                    "query_result",
                    [],
                )
                count = (
                    records[0].get("count", 0)
                    if records
                    else 0
                )
                statistics["nodes"][label] = count

        for relationship_type in sorted(
            r
            for r in relationship_types
            if r
        ):
            query = f"""
            MATCH ()-[r:`{relationship_type}]->()
            RETURN count(r) AS count
            """

            result = self.graphdb.send_query(query)

            if result.get("status") == "success":
                records = result.get(
                    "query_result",
                    [],
                )
                count = (
                    records[0].get("count", 0)
                    if records
                    else 0
                )
                statistics["relationships"][
                    relationship_type
                ] = count

        statistics["total_nodes"] = sum(
            statistics["nodes"].values()
        )

        statistics["total_relationships"] = sum(
            statistics["relationships"].values()
        )

        self.report["statistics"] = statistics

        return statistics

    # ========================================================
    # Graph Validation
    # ========================================================

    def validate_graph(
        self,
        plan: dict,
    ) -> Dict[str, Any]:
        """验证关系规则是否真的能在图中找到两端节点。"""

        errors: List[str] = []
        warnings: List[str] = []

        for key, rule in plan.items():
            if rule.get("construction_type") != "relationship":
                continue

            relationship_type = rule[
                "relationship_type"
            ]

            query = f"""
            MATCH (
                from_node:`{rule["from_node_label"]}`
            )-[r:`{relationship_type}`]->(
                to_node:`{rule["to_node_label"]}`
            )
            RETURN count(r) AS relationship_count
            """

            result = self.graphdb.send_query(query)

            if result.get("status") == "error":
                errors.append(
                    f"关系 {relationship_type} "
                    f"验证失败："
                    f"{result.get('error_message')}"
                )
                continue

            records = result.get(
                "query_result",
                [],
            )

            count = (
                records[0].get(
                    "relationship_count",
                    0,
                )
                if records
                else 0
            )

            if count == 0:
                warnings.append(
                    f"关系 {relationship_type} "
                    f"导入后没有发现任何关系。"
                )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }

    # ========================================================
    # Full Ingestion
    # ========================================================

    def ingest(
        self,
        plan: Optional[dict],
    ) -> Dict[str, Any]:
        """执行完整的 Schema → Neo4j 导入流程。"""

        self.reset()

        normalized = self.normalize_plan(plan)

        validation = self.validate_plan(
            normalized
        )

        if not validation["valid"]:
            self.status = "rejected"

            self.report["status"] = "error"

            return {
                "status": "error",
                "phase": "validation",
                "error_message": (
                    "导入前验证失败。"
                ),
                "validation": validation,
                "report": self.report,
            }

        self.status = "importing"

        # ----------------------------------------------------
        # 1. 创建约束
        # ----------------------------------------------------

        constraint_result = (
            self.create_constraints(normalized)
        )

        if constraint_result["status"] == "error":
            self.status = "error"

            self.report["status"] = "error"

            return {
                "status": "error",
                "phase": "constraint",
                "error_message": (
                    "创建 Neo4j 唯一约束失败。"
                ),
                "constraint": constraint_result,
                "report": self.report,
            }

        # ----------------------------------------------------
        # 2. 导入节点
        # ----------------------------------------------------

        node_results = {}

        for key, rule in normalized.items():
            if rule.get("construction_type") != "node":
                continue

            result = self.import_node(rule)

            node_results[key] = result

            if result.get("status") == "error":
                self.status = "error"
                self.report["status"] = "error"
                self.report["nodes"] = node_results

                return {
                    "status": "error",
                    "phase": "node_import",
                    "failed_rule": key,
                    "error_message": result.get(
                        "error_message"
                    ),
                    "report": self.report,
                }

        self.report["nodes"] = node_results

        # ----------------------------------------------------
        # 3. 导入关系
        # ----------------------------------------------------

        relationship_results = {}

        for key, rule in normalized.items():
            if (
                rule.get("construction_type")
                != "relationship"
            ):
                continue

            result = self.import_relationship(
                rule
            )

            relationship_results[key] = result

            if result.get("status") == "error":
                self.status = "error"
                self.report["status"] = "error"
                self.report[
                    "relationships"
                ] = relationship_results

                return {
                    "status": "error",
                    "phase": "relationship_import",
                    "failed_rule": key,
                    "error_message": result.get(
                        "error_message"
                    ),
                    "report": self.report,
                }

        self.report[
            "relationships"
        ] = relationship_results

        # ----------------------------------------------------
        # 4. 图验证
        # ----------------------------------------------------

        graph_validation = self.validate_graph(
            normalized
        )

        self.report[
            "graph_validation"
        ] = graph_validation

        # ----------------------------------------------------
        # 5. 统计
        # ----------------------------------------------------

        statistics = self.collect_statistics(
            normalized
        )

        self.report["statistics"] = statistics

        # ----------------------------------------------------
        # 6. Final
        # ----------------------------------------------------

        if graph_validation["valid"]:
            self.status = "success"
            self.report["status"] = "success"
        else:
            self.status = "warning"
            self.report["status"] = "warning"

        return {
            "status": (
                "success"
                if self.status == "success"
                else "warning"
            ),
            "report": self.report,
        }

    # ========================================================
    # Snapshot
    # ========================================================

    def get_report(self) -> Dict[str, Any]:
        """获取当前导入报告。"""

        return {
            "status": self.status,
            **self.report,
        }


__all__ = [
    "IngestionEngine",
]