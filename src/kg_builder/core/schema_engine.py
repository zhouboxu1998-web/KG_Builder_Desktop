"""
KG Builder Schema Engine。

Phase 3 核心模块。

职责：

    1. 接收 Agent 提议的 Schema。
    2. 规范化 Schema。
    3. 对 Schema 做确定性的结构检查。
    4. 保存 proposed / validation / approved 状态。
    5. 提供统一的 Schema snapshot。

重要设计：

    LLM Agent 负责：

        Schema 推理
        Schema 提议
        Schema Critic

    SchemaEngine 负责：

        Schema 数据结构
        Schema Normalize
        Schema Structural Validation
        Schema Approval

因此：

        Agent
          ↓
        SchemaEngine
          ↓
        Pipeline State

而不是：

        Agent Session
          ↓
        Pipeline 私有变量
          ↓
        UI 自己解释 Schema
"""


from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional, Set


class SchemaEngine:
    """
    Schema 的确定性业务引擎。

    不负责：

        - LLM 调用
        - Agent 调用
        - Neo4j 写入
        - Pipeline Runtime

    只负责 Schema。
    """

    VALID_CONSTRUCTION_TYPES = {
        "node",
        "relationship",
    }

    VALID_STATUSES = {
        "pending",
        "proposed",
        "validated",
        "approved",
        "rejected",
    }

    def __init__(self) -> None:

        self.reset()

    # ========================================================
    # Lifecycle
    # ========================================================

    def reset(self) -> None:
        """
        重置 Schema Engine。

        注意：

            这里只清理 Schema 业务状态。

            不影响 PipelineRuntime。
            不影响 AgentRuntime。
        """

        self.status = "pending"

        self.proposed_plan: Dict[str, Dict[str, Any]] = {}

        self.normalized_plan: Dict[
            str,
            Dict[str, Any],
        ] = {}

        self.validation: Dict[str, Any] = {
            "valid": False,
            "errors": [],
            "warnings": [],
        }

        self.validation_feedback: List[str] = []

        self.approved_plan: Optional[
            Dict[str, Dict[str, Any]]
        ] = None

    # ========================================================
    # Proposal
    # ========================================================

    def set_proposed_plan(
        self,
        plan: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        设置 Agent 提议的 Schema。

        这里不会直接批准 Schema。

        流程：

            proposed
                ↓
            normalize
                ↓
            validate
                ↓
            approve
        """

        if plan is None:
            plan = {}

        if not isinstance(plan, dict):
            raise TypeError(
                "Schema plan 必须是 dict。"
            )

        self.proposed_plan = deepcopy(
            plan
        )

        self.normalized_plan = (
            self.normalize_plan(
                self.proposed_plan
            )
        )

        self.status = "proposed"

        self.validation = {
            "valid": False,
            "errors": [],
            "warnings": [],
        }

        self.validation_feedback = []

        self.approved_plan = None

        return deepcopy(
            self.normalized_plan
        )

    # ========================================================
    # Normalize
    # ========================================================

    def normalize_plan(
        self,
        plan: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        """
        规范化 Schema。

        不改变 Schema 的业务语义。

        只统一：

            dict
            list
            string
            properties

        的表示方式。
        """

        if not isinstance(plan, dict):
            raise TypeError(
                "Schema plan 必须是 dict。"
            )

        normalized: Dict[
            str,
            Dict[str, Any],
        ] = {}

        for key, raw_rule in plan.items():

            if not isinstance(
                raw_rule,
                dict,
            ):
                continue

            rule = deepcopy(
                raw_rule
            )

            # ------------------------------------------------
            # construction_type
            # ------------------------------------------------

            construction_type = str(
                rule.get(
                    "construction_type",
                    "",
                )
            ).strip().lower()

            rule[
                "construction_type"
            ] = construction_type

            # ------------------------------------------------
            # properties
            # ------------------------------------------------

            properties = rule.get(
                "properties",
                [],
            )

            if properties is None:
                properties = []

            if isinstance(
                properties,
                str,
            ):
                properties = [
                    properties
                ]

            elif not isinstance(
                properties,
                list,
            ):
                properties = list(
                    properties
                )

            rule[
                "properties"
            ] = [
                str(item)
                for item in properties
            ]

            # ------------------------------------------------
            # 字段字符串清理
            # ------------------------------------------------

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

            for field_name in string_fields:

                if field_name in rule:

                    value = rule[
                        field_name
                    ]

                    if value is None:
                        rule[field_name] = ""

                    else:
                        rule[field_name] = str(
                            value
                        ).strip()

            # ------------------------------------------------
            # 使用规则 key 作为最终 plan key
            # ------------------------------------------------

            plan_key = str(
                key
            ).strip()

            if not plan_key:

                if construction_type == "node":

                    plan_key = rule.get(
                        "label",
                        "",
                    )

                elif (
                    construction_type
                    == "relationship"
                ):

                    plan_key = rule.get(
                        "relationship_type",
                        "",
                    )

            if not plan_key:
                continue

            normalized[
                plan_key
            ] = rule

        return normalized

    # ========================================================
    # Validation
    # ========================================================

    def validate(
        self,
        plan: Optional[
            Dict[str, Any]
        ] = None,
    ) -> Dict[str, Any]:
        """
        对 Schema 进行确定性结构验证。

        注意：

            这里不使用 LLM。

            这是 Schema Engine 最重要的职责。
        """

        if plan is None:
            plan = self.normalized_plan

        normalized = self.normalize_plan(
            plan
        )

        errors: List[str] = []

        warnings: List[str] = []

        # ----------------------------------------------------
        # 基础检查
        # ----------------------------------------------------

        if not normalized:

            errors.append(
                "Schema 构建计划为空。"
            )

        # ----------------------------------------------------
        # 收集节点
        # ----------------------------------------------------

        node_labels: Set[str] = set()

        relationship_types: Set[str] = set()

        # ----------------------------------------------------
        # 第一遍：
        # 检查规则本身
        # ----------------------------------------------------

        for key, rule in normalized.items():

            construction_type = rule.get(
                "construction_type"
            )

            if construction_type not in (
                self.VALID_CONSTRUCTION_TYPES
            ):

                errors.append(
                    f"构建规则 '{key}' 的 "
                    f"construction_type 无效："
                    f"{construction_type!r}"
                )

                continue

            # =================================================
            # Node
            # =================================================

            if construction_type == "node":

                label = rule.get(
                    "label",
                    "",
                )

                unique_column_name = (
                    rule.get(
                        "unique_column_name",
                        "",
                    )
                )

                source_file = rule.get(
                    "source_file",
                    "",
                )

                if not label:

                    errors.append(
                        f"节点 '{key}' 缺少 label。"
                    )

                else:

                    if label in node_labels:

                        errors.append(
                            f"节点 label 重复："
                            f"{label}"
                        )

                    node_labels.add(
                        label
                    )

                if not unique_column_name:

                    errors.append(
                        f"节点 '{key}' 缺少 "
                        "unique_column_name。"
                    )

                if not source_file:

                    warnings.append(
                        f"节点 '{key}' 没有 source_file。"
                    )

            # =================================================
            # Relationship
            # =================================================

            elif (
                construction_type
                == "relationship"
            ):

                relationship_type = (
                    rule.get(
                        "relationship_type",
                        "",
                    )
                )

                from_node_label = (
                    rule.get(
                        "from_node_label",
                        "",
                    )
                )

                from_node_column = (
                    rule.get(
                        "from_node_column",
                        "",
                    )
                )

                to_node_label = (
                    rule.get(
                        "to_node_label",
                        "",
                    )
                )

                to_node_column = (
                    rule.get(
                        "to_node_column",
                        "",
                    )
                )

                if not relationship_type:

                    errors.append(
                        f"关系 '{key}' 缺少 "
                        "relationship_type。"
                    )

                else:

                    if (
                        relationship_type
                        in relationship_types
                    ):

                        errors.append(
                            f"关系类型重复："
                            f"{relationship_type}"
                        )

                    relationship_types.add(
                        relationship_type
                    )

                if not from_node_label:

                    errors.append(
                        f"关系 '{key}' 缺少 "
                        "from_node_label。"
                    )

                if not from_node_column:

                    errors.append(
                        f"关系 '{key}' 缺少 "
                        "from_node_column。"
                    )

                if not to_node_label:

                    errors.append(
                        f"关系 '{key}' 缺少 "
                        "to_node_label。"
                    )

                if not to_node_column:

                    errors.append(
                        f"关系 '{key}' 缺少 "
                        "to_node_column。"
                    )

                if not source_file:

                    warnings.append(
                        f"关系 '{key}' 没有 source_file。"
                    )

        # ----------------------------------------------------
        # 第二遍：
        # 检查 Relationship 引用的 Node
        # ----------------------------------------------------

        for key, rule in normalized.items():

            if (
                rule.get(
                    "construction_type"
                )
                != "relationship"
            ):
                continue

            from_label = rule.get(
                "from_node_label"
            )

            to_label = rule.get(
                "to_node_label"
            )

            if (
                from_label
                and from_label not in node_labels
            ):

                errors.append(
                    f"关系 '{key}' 引用了"
                    f"不存在的源节点："
                    f"{from_label}"
                )

            if (
                to_label
                and to_label not in node_labels
            ):

                errors.append(
                    f"关系 '{key}' 引用了"
                    f"不存在的目标节点："
                    f"{to_label}"
                )

        # ----------------------------------------------------
        # 第三遍：
        # 检查孤立节点
        # ----------------------------------------------------

        connected_labels: Set[str] = set()

        for rule in normalized.values():

            if (
                rule.get(
                    "construction_type"
                )
                != "relationship"
            ):
                continue

            from_label = rule.get(
                "from_node_label"
            )

            to_label = rule.get(
                "to_node_label"
            )

            if from_label:
                connected_labels.add(
                    from_label
                )

            if to_label:
                connected_labels.add(
                    to_label
                )

        if len(node_labels) > 1:

            isolated_nodes = (
                node_labels
                - connected_labels
            )

            for label in sorted(
                isolated_nodes
            ):

                warnings.append(
                    f"节点 '{label}' "
                    "当前没有关系连接。"
                )

        # ----------------------------------------------------
        # 最终结果
        # ----------------------------------------------------

        valid = (
            len(errors) == 0
        )

        self.validation = {
            "valid": valid,
            "errors": errors,
            "warnings": warnings,
        }

        self.validation_feedback = (
            list(errors)
        )

        self.normalized_plan = (
            normalized
        )

        if valid:

            self.status = "validated"

        else:

            self.status = "rejected"

        return deepcopy(
            self.validation
        )

    # ========================================================
    # Approve
    # ========================================================

    def approve(
        self,
        plan: Optional[
            Dict[str, Any]
        ] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        批准 Schema。

        如果传入 plan：

            先 Normalize + Validate。

        如果没有传入：

            使用当前 normalized_plan。

        只有 validation.valid == True
        才允许批准。
        """

        if plan is not None:

            self.set_proposed_plan(
                plan
            )

        if not self.normalized_plan:

            raise ValueError(
                "没有可批准的 Schema。"
            )

        validation = self.validate(
            self.normalized_plan
        )

        if not validation["valid"]:

            raise ValueError(
                "Schema 验证失败，"
                "不能批准："
                + "; ".join(
                    validation["errors"]
                )
            )

        self.approved_plan = deepcopy(
            self.normalized_plan
        )

        self.status = "approved"

        return deepcopy(
            self.approved_plan
        )

    # ========================================================
    # Query
    # ========================================================

    def is_approved(self) -> bool:
        """
        判断 Schema 是否已经批准。
        """

        return (
            self.status == "approved"
            and self.approved_plan
            is not None
        )

    def get_proposed_plan(
        self,
    ) -> Dict[str, Dict[str, Any]]:

        return deepcopy(
            self.proposed_plan
        )

    def get_normalized_plan(
        self,
    ) -> Dict[str, Dict[str, Any]]:

        return deepcopy(
            self.normalized_plan
        )

    def get_approved_plan(
        self,
    ) -> Optional[
        Dict[str, Dict[str, Any]]
    ]:

        if self.approved_plan is None:
            return None

        return deepcopy(
            self.approved_plan
        )

    def get_validation(
        self,
    ) -> Dict[str, Any]:

        return deepcopy(
            self.validation
        )

    def get_snapshot(
        self,
    ) -> Dict[str, Any]:
        """
        返回 Schema Engine 完整快照。
        """

        return {
            "status": self.status,

            "proposed": deepcopy(
                self.proposed_plan
            ),

            "normalized": deepcopy(
                self.normalized_plan
            ),

            "validation": deepcopy(
                self.validation
            ),

            "validation_feedback": list(
                self.validation_feedback
            ),

            "approved": (
                deepcopy(
                    self.approved_plan
                )
                if self.approved_plan
                is not None
                else None
            ),
        }


__all__ = [
    "SchemaEngine",
]

