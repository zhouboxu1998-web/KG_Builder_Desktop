"""所有 Agent 状态键集中定义，避免拼写错误。"""

# ============ 用户意图 ============
PERCEIVED_USER_GOAL = "perceived_user_goal"
APPROVED_USER_GOAL = "approved_user_goal"

# ============ 文件选择（旧版，保留兼容）============
ALL_AVAILABLE_FILES = "all_available_files"
SUGGESTED_FILES = "suggested_files"
APPROVED_FILES = "approved_files"

# ============ 文件选择（新版：分类）★ 新增 ============
# 结构化文件（CSV / JSON）
ALL_AVAILABLE_STRUCTURED = "all_available_structured_files"
SUGGESTED_STRUCTURED_FILES = "suggested_structured_files"
APPROVED_STRUCTURED_FILES = "approved_structured_files"

# 非结构化文件（MD / TXT）
ALL_AVAILABLE_UNSTRUCTURED = "all_available_unstructured_files"
SUGGESTED_UNSTRUCTURED_FILES = "suggested_unstructured_files"
APPROVED_UNSTRUCTURED_FILES = "approved_unstructured_files"

# ============ 结构化图谱 - 构建计划 ============
PROPOSED_CONSTRUCTION_PLAN = "proposed_construction_plan"
APPROVED_CONSTRUCTION_PLAN = "approved_construction_plan"

# ============ 非结构化图谱 - 实体与事实 ============
PROPOSED_ENTITIES = "proposed_entity_types"
APPROVED_ENTITIES = "approved_entity_types"
PROPOSED_FACTS = "proposed_fact_types"
APPROVED_FACTS = "approved_fact_types"

# ============ 反馈 ============
FEEDBACK = "feedback"