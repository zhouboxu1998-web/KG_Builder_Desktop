"""集中式配置：环境变量、路径、模型名。"""
import os
from pathlib import Path

from dotenv import load_dotenv, find_dotenv

# ---------- 路径 ----------
PACKAGE_DIR = Path(__file__).parent
PROMPTS_DIR = PACKAGE_DIR / "prompts"
PROJECT_ROOT = PACKAGE_DIR.parent.parent

# 优先明确加载项目根目录的 .env。
# 这样从 run.py / IDE / 任意工作目录启动时，都不会因为
# find_dotenv() 的搜索起点不同而漏掉项目配置。
DOTENV_PATH = PROJECT_ROOT / ".env"
if DOTENV_PATH.exists():
    load_dotenv(DOTENV_PATH, override=False)
else:
    _ = load_dotenv(find_dotenv(), override=False)


def _path_from_env(key: str, default: str) -> Path:
    raw = os.getenv(key, default)
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
    return p


IMPORT_DIR = _path_from_env("NEO4J_IMPORT_DIR", "./data/import")

# ---------- LLM ----------
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek/deepseek-chat")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# ---------- Embedding ----------
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)
EMBEDDING_MODEL = os.getenv("EMD_MODEL_NAME", "qwen3.7-text-embedding")

# ---------- Neo4j ----------
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")


def ensure_import_dir() -> Path:
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    return IMPORT_DIR

# ---------- Logging ----------
LOG_LEVEL = os.getenv("KG_LOG_LEVEL", "INFO").upper()
LOG_DIR = _path_from_env("KG_LOG_DIR", "./logs")
LOG_FILE = os.getenv("KG_LOG_FILE", "kg_builder.log")
LOG_TO_CONSOLE = os.getenv("KG_LOG_TO_CONSOLE", "true").lower() in {
    "1", "true", "yes", "on",
}
LOG_TO_FILE = os.getenv("KG_LOG_TO_FILE", "true").lower() in {
    "1", "true", "yes", "on",
}
LOG_JSON = os.getenv("KG_LOG_JSON", "true").lower() in {
    "1", "true", "yes", "on",
}
LOG_MAX_BYTES = int(
    os.getenv(
        "KG_LOG_MAX_BYTES",
        str(10 * 1024 * 1024),
    )
)
LOG_BACKUP_COUNT = int(
    os.getenv("KG_LOG_BACKUP_COUNT", "5")
)


# ---------- Retry / Timeout ----------
KG_RETRY_MAX_ATTEMPTS = int(
    os.getenv("KG_RETRY_MAX_ATTEMPTS", "1")
)
KG_RETRY_INITIAL_DELAY = float(
    os.getenv("KG_RETRY_INITIAL_DELAY", "0.5")
)
KG_RETRY_MAX_DELAY = float(
    os.getenv("KG_RETRY_MAX_DELAY", "5.0")
)
KG_RETRY_BACKOFF_MULTIPLIER = float(
    os.getenv("KG_RETRY_BACKOFF_MULTIPLIER", "2.0")
)
KG_RETRY_JITTER = float(
    os.getenv("KG_RETRY_JITTER", "0.0")
)

AGENT_TIMEOUT_SECONDS = float(
    os.getenv("KG_AGENT_TIMEOUT_SECONDS", "120")
)
QUERY_TIMEOUT_SECONDS = float(
    os.getenv("KG_QUERY_TIMEOUT_SECONDS", "30")
)
NEO4J_CONNECTION_TIMEOUT_SECONDS = float(
    os.getenv("KG_NEO4J_CONNECTION_TIMEOUT_SECONDS", "10")
)
