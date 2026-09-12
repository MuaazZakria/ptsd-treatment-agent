"""Offline test config - set env BEFORE iaso_lite.config is imported anywhere."""

import os
from pathlib import Path

FIX = Path(__file__).parent / "fixtures"

os.environ["IASO_MANUS_OFFLINE"] = "1"
os.environ.pop("MANUS_API_KEY", None)
os.environ["IASO_EVIDENCE_DIR"] = str(FIX / "corpus")
os.environ["IASO_PATIENTS_FILE"] = str(FIX / "patients.json")
os.environ["IASO_CACHE_DIR"] = str(FIX / ".cache")
os.environ["IASO_DECISIONS_DIR"] = str(FIX / ".cache" / "decisions")
os.environ["IASO_MIN_USEFUL_BM25"] = "0.0"  # the fixture corpus is tiny
os.environ.setdefault("IASO_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("IASO_SESSION_SECRET", "test-session-secret")

import shutil  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_decisions_dir():
    """Each test starts from an empty decisions/ dir (the log is append-only)."""
    from iaso_lite.config import get_settings

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
    from iaso_lite.config import get_settings
    from iaso_lite.synthesis import run_stream

    return [ev async for ev in run_stream(patient, FakeRequest(), get_settings())]


def load_fixture(patient_id: str) -> dict:
    from iaso_lite.patient import patient_by_id

    p = patient_by_id(patient_id)
    assert p is not None, patient_id
    return p
