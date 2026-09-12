import pytest

from iaso_lite import decisions
from iaso_lite.config import get_settings


def test_record_decision_writes_snapshot_and_appends_log():
    rec = decisions.record_decision(
        patient_id="pt-1",
        clinician="Dr. Rivera",
        decision="approve",
        notes="Looks right.",
        status="READY_FOR_CLINICIAN_REVIEW",
        draft={"summary": "s", "options": []},
        citation_audit={"pass": True},
        evidence_ids=["LOCAL-00001"],
        cfg=get_settings(),
    )
    assert rec["decision_id"]
    assert rec["clinician"] == "Dr. Rivera"
    assert rec["decision"] == "approve"

    cfg = get_settings()
    snapshot = cfg.decisions_dir / "pt-1" / f"decision_{rec['decision_id']}.json"
    assert snapshot.exists()

    log_path = cfg.decisions_dir / "log.jsonl"
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert any(rec["decision_id"] in line for line in lines)


def test_invalid_decision_value_rejected():
    with pytest.raises(ValueError):
        decisions.record_decision(
            patient_id="pt-1", clinician="Dr. Rivera", decision="approve-ish"
        )


def test_missing_clinician_rejected():
    with pytest.raises(ValueError):
        decisions.record_decision(patient_id="pt-1", clinician="  ", decision="approve")


def test_read_log_is_newest_first_and_respects_limit():
    for i in range(3):
        decisions.record_decision(
            patient_id="pt-2", clinician="Dr. Rivera", decision="acknowledge", notes=str(i)
        )
    rows = decisions.read_log(get_settings(), limit=2)
    assert len(rows) == 2
    assert rows[0]["notes"] == "2"
    assert rows[1]["notes"] == "1"
