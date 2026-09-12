from conftest import drain, load_fixture


async def test_flagged_patient_escalates_and_never_calls_manus():
    events = await drain(load_fixture("fixture-flagged-02"))
    names = [n for n, _ in events]

    assert "stage" in names
    assert ("stage", "escalated") in [(n, p.get("state")) for n, p in events]

    # no retrieval, no synthesis, no draft once the gate escalates
    stage_ids = [p.get("id") for n, p in events if n == "stage"]
    assert "retrieve" not in stage_ids
    assert "synthesis" not in stage_ids
    assert "draft" not in names

    name, payload = events[-1]
    assert name == "done"
    assert payload["status"] == "STOPPED_FOR_CLINICIAN_REVIEW"
    assert payload["manus_called"] is False


async def test_missing_required_field_escalates():
    events = await drain({"patient_id": "x", "ptsd": {"still_active": True}})  # no `treatment`
    name, payload = events[-1]
    assert name == "done"
    assert payload["status"] == "STOPPED_FOR_CLINICIAN_REVIEW"
    gate = next(p["gate"] for n, p in events if n == "stage" and "gate" in p)
    assert gate["valid"] is False
    assert "treatment" in gate["missing_required_fields"]
