from conftest import drain, load_fixture


def _subsequence(names: list[str], want: list[str]) -> bool:
    it = iter(names)
    return all(w in it for w in want)


async def test_run_stream_order_and_offline_stub():
    events = await drain(load_fixture("fixture-routine-01"))
    names = [n for n, _ in events]

    stage_states = [
        f"{p['id']}:{p['state']}" for n, p in events if n == "stage" and "state" in p
    ]
    assert _subsequence(
        stage_states,
        ["safety:done", "query:done", "retrieve:done", "synthesis:running", "synthesis:done"],
    )
    assert _subsequence(names, ["draft", "citation_audit", "done"])

    draft = next(p for n, p in events if n == "draft")
    assert draft["source"] == "offline_stub"

    retrieved = {
        e["evidence_id"]
        for n, p in events
        if n == "stage" and p.get("id") == "retrieve"
        for e in p["evidence"]
    }
    for o in draft["recommended_plan"]:
        assert set(o["ev"]) <= retrieved

    done = next(p for n, p in events if n == "done")
    assert set(done["timings"]) >= {"safety", "query", "retrieve", "synthesis", "audit", "total"}
    assert done["manus_called"] is False


async def test_offline_stub_is_clearly_marked():
    events = await drain(load_fixture("fixture-routine-01"))
    draft = next(p for n, p in events if n == "draft")
    assert "[OFFLINE STUB]" in draft["assessment"]
    assert draft["recommended_plan"] and "[OFFLINE STUB]" in draft["recommended_plan"][0]["text"]
