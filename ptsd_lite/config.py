"""
Runtime configuration, read once from the environment.

Retrieval knobs keep sensible verbatim defaults from the original pipeline
this was trimmed from; the TensorX / PubMed / decisions knobs are gone and
Manus knobs take their place. When no MANUS_API_KEY is set (or
PTA_MANUS_OFFLINE=1) the synthesis step falls back to a deterministic stub
so the whole app still runs end to end.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent          # ptsd-treatment-agent/
PROJECT_ROOT = REPO_ROOT.parent


def _first_existing(*candidates: Path) -> Path:
    for c in candidates:
        if c.exists():
            return c
    return candidates[-1]


def _env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    return Path(raw).expanduser().resolve() if raw else default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # --- Manus API -----------------------------------------------------------
    manus_api_key: str = os.getenv("MANUS_API_KEY", "").strip()
    manus_base_url: str = os.getenv("MANUS_BASE_URL", "https://api.manus.ai/v2")
    manus_agent_profile: str = os.getenv("MANUS_AGENT_PROFILE", "lite").strip() or "lite"
    manus_poll_interval_s: float = float(os.getenv("MANUS_POLL_INTERVAL_S", "2.5"))
    manus_stream_max_s: float = float(os.getenv("MANUS_STREAM_MAX_S", "1800"))

    offline: bool = _env_bool("PTA_MANUS_OFFLINE", False)

    # --- retrieval knobs (verbatim defaults from the original pipeline) -----------
    top_k_local: int = int(os.getenv("PTA_TOP_K_LOCAL", "3"))
    max_queries: int = int(os.getenv("PTA_MAX_QUERIES", "2"))
    max_final_evidence: int = int(os.getenv("PTA_MAX_FINAL_EVIDENCE", "5"))
    evidence_chars: int = int(os.getenv("PTA_EVIDENCE_CHARS", "650"))
    min_useful_bm25: float = float(os.getenv("PTA_MIN_USEFUL_BM25", "1.0"))

    chunk_words: int = int(os.getenv("PTA_CHUNK_WORDS", "180"))
    overlap_words: int = int(os.getenv("PTA_OVERLAP_WORDS", "30"))
    min_chunk_words: int = int(os.getenv("PTA_MIN_CHUNK_WORDS", "50"))

    # --- paths -------------------------------------------------------------
    evidence_dir: Path = field(
        default_factory=lambda: _env_path(
            "PTA_EVIDENCE_DIR",
            _first_existing(
                PROJECT_ROOT / "ptsd_evidence_corpus",
                REPO_ROOT / "ptsd_evidence_corpus",
                REPO_ROOT / "data" / "evidence",
            ),
        )
    )
    patients_file: Path = field(
        default_factory=lambda: _env_path(
            "PTA_PATIENTS_FILE",
            _first_existing(
                PROJECT_ROOT / "ptsd_veteran_US_profiles.json",
                REPO_ROOT / "data" / "patients" / "ptsd_veteran_US_profiles.json",
                REPO_ROOT / "data" / "patients" / "patients.json",
            ),
        )
    )
    cache_dir: Path = field(
        default_factory=lambda: _env_path("PTA_CACHE_DIR", REPO_ROOT / ".cache")
    )

    # --- web app ---------------------------------------------------------
    demo_patient_limit: int = int(os.getenv("PTA_DEMO_PATIENT_LIMIT", "60"))

    # --- admin login + decisions --------------------------------------------
    # One shared admin password gating the app - not real IAM, no user
    # identity beyond "the admin". See ptsd_lite/auth.py.
    admin_password: str = os.getenv("PTA_ADMIN_PASSWORD", "").strip()
    session_secret: str = field(
        default_factory=lambda: os.getenv("PTA_SESSION_SECRET", "").strip()
        or secrets.token_hex(32)
    )
    decisions_dir: Path = field(
        default_factory=lambda: _env_path("PTA_DECISIONS_DIR", REPO_ROOT / "decisions")
    )

    # --- cross-origin frontend (e.g. Vercel frontend + tunnelled backend) ---
    # Comma-separated list of allowed origins, e.g. "https://your-frontend.vercel.app".
    # Non-empty => CORS is enabled and the session cookie switches to
    # SameSite=None; Secure (required for cross-site cookies).
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip() for o in os.getenv("PTA_CORS_ORIGINS", "").split(",") if o.strip()
        )
    )

    def __post_init__(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.decisions_dir.mkdir(parents=True, exist_ok=True)
        if not self.admin_password:
            print(
                "[config] WARNING: PTA_ADMIN_PASSWORD is not set - "
                "every /api/* route is running without a login gate."
            )
        elif not os.getenv("PTA_SESSION_SECRET"):
            print(
                "[config] PTA_SESSION_SECRET not set - generated a random one for "
                "this process. Every session is invalidated on restart."
            )

    @property
    def auth_enabled(self) -> bool:
        return bool(self.admin_password)

    @property
    def manus_available(self) -> bool:
        return bool(self.manus_api_key) and not self.offline


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
