"""Settings: credentials from the project's .env, model names and decision thresholds."""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"
DATA_DIR = PROJECT_ROOT / "data"
CATALOG_PATH = DATA_DIR / "catalog.json"
CHROMA_DIR = DATA_DIR / "chroma"
# Per-home files, gitignored; the *.example.yaml next to them are the committed templates.
ALIASES_PATH = PROJECT_ROOT / "aliases.yaml"
EVAL_PATH = PROJECT_ROOT / "eval" / "commands.yaml"


def load_env_file(path=ENV_PATH):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    embed_model: str = "BAAI/bge-m3"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    typesafe_model: str | None = None  # None = the API's default (latest Jev)
    retrieve_k: int = 30
    rerank_k: int = 5
    min_confidence: float = 0.8
    # Eval showed the Choice (with its "none" option) carries the decision; per-candidate fits nouls
    # were systematically low for brand-name aliases and never caught a wrong action, so they are
    # reported but don't gate. The home-command gate only vetoes clear chit-chat.
    min_fits: float = 0.0
    min_gate: float = 0.2

    @classmethod
    def from_env(cls):
        load_env_file()
        return cls(
            typesafe_model=os.environ.get("TYPESAFE_MODEL") or None,
            min_confidence=float(os.environ.get("DECISION_MIN_CONFIDENCE", cls.min_confidence)),
        )


def get_session():
    load_env_file()
    base_url = os.environ.get("HA_URL")
    token = os.environ.get("HA_TOKEN")
    if not base_url or not token:
        sys.exit(
            "Missing HA_URL and/or HA_TOKEN. Set them as environment variables "
            f"or in {ENV_PATH}."
        )
    session = requests.Session()
    session.headers.update(
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    return session, base_url.rstrip("/")


def aliases_path():
    load_env_file()
    return Path(os.environ.get("DECISION_ALIASES") or ALIASES_PATH)


def eval_path():
    load_env_file()
    return Path(os.environ.get("DECISION_EVAL") or EVAL_PATH)


def api_token():
    """Bearer token for `decide serve`; None = no token (then the server refuses execute)."""
    load_env_file()
    return os.environ.get("DECISION_API_TOKEN") or None


def require_typesafe_key():
    load_env_file()
    if not os.environ.get("TYPESAFE_API_KEY"):
        sys.exit(f"Missing TYPESAFE_API_KEY. Add it to {ENV_PATH}.")
