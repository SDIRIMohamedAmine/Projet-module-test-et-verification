import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent
STORAGE_DIR = ROOT_DIR / "storage"
EVIDENCE_DIR = STORAGE_DIR / "evidence"
REPORTS_DIR = STORAGE_DIR / "reports"

load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@localhost:5432/agent_e2e",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_SORT_KEYS = False

    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    GROQ_MODEL = os.environ.get("GROQ_MODEL", "mimo-v2.6-flash")
    GROQ_BASE_URL = os.environ.get(
        "GROQ_BASE_URL", "https://api.groq.com/openai/v1"
    )

    EVIDENCE_DIR = str(EVIDENCE_DIR)
    REPORTS_DIR = str(REPORTS_DIR)

    DEFAULT_EXPLORATION_LIMITS = {
        "max_pages": 15,
        "max_depth": 3,
        "max_duration_seconds": 120,
        "max_actions": 100,
        "action_timeout_ms": 8000,
    }


for _dir in (EVIDENCE_DIR, REPORTS_DIR):
    _dir.mkdir(parents=True, exist_ok=True)
