import re

from conftest import drain, load_fixture


async def test_ssri_plus_active_ptsd_adds_next_line_query_without_dropping_the_drug_query():
    """PTSD still active despite an SSRI = inadequate response - the treatment-
    resistant query should be ADDED alongside the standard drug/comorbidity
    queries, not replace them (regression: replacing them meant every
    sertraline patient - still_active is true for ~all of them in this
    synthetic dataset - lost the query that actually retrieves direct
    PTSD-treatment evidence)."""
    events = await drain(load_fixture("fixture-routine-01"))  # sertraline, still_active=true

    queries = next(p["queries"] for n, p in events if n == "stage" and p.get("id") == "query")
    assert any("sertraline" in q for q in queries)
    assert any("isolation" in q for q in queries)
    assert any("treatment-resistant" in q for q in queries)
    assert len(queries) == 3

    retrieve = next(p for n, p in events if n == "stage" and p.get("id") == "retrieve")
    assert retrieve["evidence"], "expected at least one retrieved passage"
    for e in retrieve["evidence"]:
        assert re.fullmatch(r"LOCAL-\d{5}", e["evidence_id"])
        assert e["text"]
    assert retrieve["retrieval_meta"]["n_local"] == len(retrieve["evidence"])


async def test_ssri_with_ptsd_in_remission_uses_plain_efficacy_query_only():
    """Same drug, but PTSD is no longer active - not the treatment-resistant
    case, so no extra query is added."""
    events = await drain(load_fixture("fixture-remission-03"))  # sertraline, still_active=false

    queries = next(p["queries"] for n, p in events if n == "stage" and p.get("id") == "query")
    assert any("sertraline" in q for q in queries)
    assert not any("treatment-resistant" in q for q in queries)
    assert len(queries) == 2
