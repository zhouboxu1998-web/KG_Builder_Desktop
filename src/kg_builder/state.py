"""所有 Agent 状态键集中定义，避免拼写错误。"""

PERCEIVED_USER_GOAL = "perceived_user_goal"
APPROVED_USER_GOAL = "approved_user_goal"

ALL_AVAILABLE_FILES = "all_available_files"
SUGGESTED_FILES = "suggested_files"
APPROVED_FILES = "approved_files"

ALL_AVAILABLE_STRUCTURED = "all_available_structured_files"
SUGGESTED_STRUCTURED_FILES = "suggested_structured_files"
APPROVED_STRUCTURED_FILES = "approved_structured_files"

ALL_AVAILABLE_UNSTRUCTURED = "all_available_unstructured_files"
SUGGESTED_UNSTRUCTURED_FILES = "suggested_unstructured_files"
APPROVED_UNSTRUCTURED_FILES = "approved_unstructured_files"

PROPOSED_CONSTRUCTION_PLAN = "proposed_construction_plan"
APPROVED_CONSTRUCTION_PLAN = "approved_construction_plan"

PROPOSED_ENTITIES = "proposed_entity_types"
APPROVED_ENTITIES = "approved_entity_types"
PROPOSED_FACTS = "proposed_fact_types"
APPROVED_FACTS = "approved_fact_types"

FEEDBACK = "feedback"

# ============================================================
# Phase 3：Schema Engine
# ============================================================

SCHEMA_NORMALIZED_PLAN = "schema_normalized_plan"
SCHEMA_VALIDATION = "schema_validation"
SCHEMA_VALIDATION_FEEDBACK = "schema_validation_feedback"
SCHEMA_APPROVED_PLAN = "schema_approved_plan"
SCHEMA_STATUS = "schema_status"

# ============================================================
# Phase 4：Ingestion Engine
# ============================================================

INGESTION_STATUS = "ingestion_status"
INGESTION_REPORT = "ingestion_report"
INGESTION_ERRORS = "ingestion_errors"
INGESTION_WARNINGS = "ingestion_warnings"
INGESTION_STATS = "ingestion_stats"