from iaso_lite.synthesis import _normalize_draft, citation_check, evidence_quality_audit


def test_valid_citation_passes():
    a = citation_check([{"id": "MO1", "ev": ["LOCAL-00001"]}], {"LOCAL-00001", "LOCAL-00002"})
    assert a["audited"] is True
    assert a["pass"] is True
    assert a["invalid_evidence_ids"] == []


def test_fabricated_id_is_caught():
    # the Requirements Doc "planted error" criterion
    a = citation_check([{"id": "MO1", "ev": ["LOCAL-99999-not-real"]}], {"LOCAL-00001"})
    assert a["invalid_evidence_ids"] == ["LOCAL-99999-not-real"]
    assert a["pass"] is False


def test_option_without_any_citation_is_caught():
    a = citation_check([{"id": "MO1", "ev": []}], {"LOCAL-00001"})
    assert a["options_without_evidence_ids"] == ["MO1"]
    assert a["pass"] is False


def test_empty_draft_is_not_a_vacuous_pass():
    a = citation_check([], set())
    assert a["audited"] is False
    assert a["pass"] is False


def test_high_confidence_backed_only_by_animal_titles_is_flagged():
    plan = [{"id": "MO1", "conf": "high", "ev": ["LOCAL-00001"]}]
    ev = [{"evidence_id": "LOCAL-00001", "title": "Fear extinction in a mouse model of PTSD"}]
    q = evidence_quality_audit(plan, ev)
    assert q["weak_confidence_items"] == ["MO1"]


def test_high_confidence_with_one_clinical_title_is_not_flagged():
    plan = [{"id": "MO1", "conf": "high", "ev": ["LOCAL-00001", "LOCAL-00002"]}]
    ev = [
        {"evidence_id": "LOCAL-00001", "title": "Fear extinction in a mouse model of PTSD"},
        {"evidence_id": "LOCAL-00002", "title": "Sertraline for PTSD: a randomized controlled trial"},
    ]
    q = evidence_quality_audit(plan, ev)
    assert q["weak_confidence_items"] == []


def test_low_confidence_animal_evidence_is_not_flagged():
    # low confidence is already the honest signal - nothing to backstop.
    plan = [{"id": "MO1", "conf": "low", "ev": ["LOCAL-00001"]}]
    ev = [{"evidence_id": "LOCAL-00001", "title": "Fear extinction in a mouse model of PTSD"}]
    q = evidence_quality_audit(plan, ev)
    assert q["weak_confidence_items"] == []


def test_bracket_wrapped_citations_are_normalized_away():
    # the model sometimes copies evidence.txt's own "[LOCAL-00042]" header
    # formatting into the citation itself - strip it so a cosmetic slip
    # doesn't fail the citation check on an otherwise-valid id.
    raw = {
        "recommended_plan": [
            {"id": "MO1", "ev": ["[LOCAL-00001]", "LOCAL-00002"], "conf": "low"},
        ]
    }
    draft = _normalize_draft(raw)
    assert draft["recommended_plan"][0]["ev"] == ["LOCAL-00001", "LOCAL-00002"]
