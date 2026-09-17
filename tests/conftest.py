"""Offline test config - set env BEFORE ptsd_lite.config is imported anywhere."""

import os
from pathlib import Path

FIX = Path(__file__).parent / "fixtures"

os.environ["PTA_MANUS_OFFLINE"] = "1"
os.environ.pop("MANUS_API_KEY", None)
os.environ["PTA_EVIDENCE_DIR"] = str(FIX / "corpus")
os.environ["PTA_PATIENTS_FILE"] = str(FIX / "patients.json")
os.environ["PTA_CACHE_DIR"] = str(FIX / ".cache")
os.environ["PTA_DECISIONS_DIR"] = str(FIX / ".cache" / "decisions")
os.environ["PTA_MIN_USEFUL_BM25"] = "0.0"  # the fixture corpus is tiny
os.environ.setdefault("PTA_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("PTA_SESSION_SECRET", "test-session-secret")

import shutil  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_decisions_dir():
    """Each test starts from an empty decisions/ dir (the log is append-only)."""
    from ptsd_lite.config import get_settings

    d = get_settings().decisions_dir
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    yield
    shutil.rmtree(d, ignore_errors=True)


class FakeRequest:
    async def is_disconnected(self) -> bool:
        return False


@pytest.fixture
def fake_request() -> FakeRequest:
    return FakeRequest()


async def drain(patient: dict) -> list[tuple[str, dict]]:
    from ptsd_lite.config import get_settings
    from ptsd_lite.synthesis import run_stream

    return [ev async for ev in run_stream(patient, FakeRequest(), get_settings())]


def load_fixture(patient_id: str) -> dict:
    from ptsd_lite.patient import patient_by_id

    p = patient_by_id(patient_id)
    assert p is not None, patient_id
    return p
