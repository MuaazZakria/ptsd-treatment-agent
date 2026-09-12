"""
The /api/run orchestrator.

Runs the deterministic IASO stages in code (safety gate -> rule-based queries ->
local BM25 retrieval) and hands ONLY the retrieved passages to a single Manus
task for appraisal + drafting, relaying Manus's working events live. A
deterministic citation check then runs on Manus's output.

Non-negotiables kept here:
- the safety gate runs before Manus is ever called;
- every option's cited evidence_id is checked against the retrieved set by
  `citation_check` (set arithmetic) - the model never certifies itself.
"""

from __future__ import annotations

import base64
import json
from time import perf_counter
from typing import Any, AsyncIterator

from . import manus_client
from .config import Settings, get_settings
from .jsonrepair import extract_json
from .patient import compact_evidence, compact_patient_view, deterministic_patient_gate
from .prompts import MANUS_PROMPT, OPTIONS_SCHEMA
from .retrieval import build_fast_queries, search_local_corpus

Event = tuple[str, dict]

_EVIDENCE_TEXT_CAP = 900  # per passage, in the attached evidence.txt


# --------------------------------------------------------------------------- #
# deterministic helpers
# --------------------------------------------------------------------------- #

def _merge_groups(groups: list[list[dict]], limit: int) -> list[dict]:
    """Round-robin by rank across per-query groups, dedupe on evidence_id."""
    merged: list[dict] = []
    seen: set[str] = set()
    depth = max((len(g) for g in groups), default=0)
    for rank in range(depth):
        for g in groups:
            if rank < len(g):
                e = g[rank]
                eid = e.get("evidence_id")
                if eid and eid not in seen:
                    seen.add(eid)
                    merged.append(e)
    return merged[:limit]


# Keyword heuristic for "this passage is mechanistic/animal-model, not direct
# clinical treatment evidence" - a deterministic backstop for the prompt rule
# in prompts.py asking Manus not to let this kind of evidence justify a
# high/moderate confidence on its own. Same spirit as citation_check: warn,
# don't fabricate a judgment the model didn't make, and never hard-block.
_MECHANISTIC_TITLE_KEYWORDS = (
    "mice", "mouse", "rat ", "rats ", "rodent", "in vivo", "in vitro",
    "voxel-based morphometry", "neuroimaging", "fmri", "amygdala",
    "hippocampus", "biomarker", "proteome", "transcriptomic", "epigenetics",
    "connectivity", "neural correlates", "neural network",
)


def evidence_quality_audit(plan: list[dict], compact_ev: list[dict]) -> dict:
    """Flags plan items whose conf is high/moderate but whose cited evidence
    all looks mechanistic/animal-model by title - a backstop for the prompt
    rule, not a replacement for it. Warn-only: never changes `conf` or blocks
    the plan, just surfaces items worth a clinician's extra scrutiny."""
    title_by_id = {e["evidence_id"]: (e.get("title") or "").lower() for e in compact_ev if e.get("evidence_id")}
    weak_confidence_items: list[str] = []
    for o in plan or []:
        if o.get("conf") not in ("high", "moderate"):
            continue
        ids = [x for x in (o.get("ev") or []) if x]
        titles = [title_by_id.get(i, "") for i in ids]
        if titles and all(any(k in t for k in _MECHANISTIC_TITLE_KEYWORDS) for t in titles):
            weak_confidence_items.append(o.get("id") or "?")
    return {"weak_confidence_items": weak_confidence_items}


def citation_check(options: list[dict], retrieved_ids: set[str]) -> dict:
    """Mirrors iaso-ptsd-agent/iaso/graph.py audit_node (deterministic)."""
    used: list[str] = []
    uncited: list[str] = []
    for o in options or []:
        ids = [x for x in (o.get("ev") or []) if x]
        used.extend(ids)
        if not ids:
            uncited.append(o.get("id") or "?")
    invalid = sorted(set(used) - retrieved_ids)
    has_draft = bool(options)
    return {
        "invalid_evidence_ids": invalid,
        "options_without_evidence_ids": uncited,
        "pass": has_draft and not invalid and not uncited,
        "audited": has_draft,
    }


def offline_stub(patient_compact: dict, compact_ev: list[dict]) -> dict:
    """Deterministic placeholder - mirrors iaso/llm.py::_offline_stub."""
    ev_ids = [e["evidence_id"] for e in compact_ev if e.get("evidence_id")]
    return {
        "assessment": "[OFFLINE STUB] No MANUS_API_KEY configured - placeholder output "
        f"so the pipeline and UI run end to end. Retrieved {len(compact_ev)} passage(s); "
        "Manus was not called.",
        "recommended_plan": (
            [
                {
                    "id": "MO1",
                    "cat": "offline-stub",
                    "text": "[OFFLINE STUB] Trauma-focused psychotherapy as a first-line option.",
                    "rationale": "Deterministic placeholder - no agent reasoning was performed.",
                    "ev": ev_ids[:2],
                    "cautions": ["Not a real synthesis. For pipeline wiring / demo layout only."],
                    "conf": "low",
                }
            ]
            if ev_ids
            else []
        ),
        "monitoring": [],
        "reassessment_triggers": [],
        "missing": ["A configured MANUS_API_KEY for a genuine evidence synthesis."],
        "source": "offline_stub",
    }


def _normalize_draft(raw: dict | None) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    plan = []
    for o in raw.get("recommended_plan") or []:
        if not isinstance(o, dict):
            continue
        plan.append(
            {
                "id": str(o.get("id") or f"MO{len(plan) + 1}"),
                "cat": str(o.get("cat") or ""),
                "text": str(o.get("text") or ""),
                "rationale": str(o.get("rationale") or ""),
                # strip accidental "[LOCAL-00042]" bracket-wrapping - the model
                # sometimes copies evidence.txt's own header formatting into
                # the citation despite the prompt asking for the bare id.
                "ev": [str(x).strip().strip("[]") for x in (o.get("ev") or []) if x],
                "cautions": [str(x) for x in (o.get("cautions") or []) if x],
                "conf": o.get("conf") if o.get("conf") in ("high", "moderate", "low") else "low",
            }
        )
    return {
        "assessment": str(raw.get("assessment") or ""),
        "recommended_plan": plan,
        "monitoring": [str(x) for x in (raw.get("monitoring") or []) if x],
        "reassessment_triggers": [str(x) for x in (raw.get("reassessment_triggers") or []) if x],
        "missing": [str(x) for x in (raw.get("missing") or []) if x],
    }


def _patient_brief(pc: dict) -> str:
    """Short readable patient line - keeps the Manus message small."""
    ptsd = pc.get("ptsd") or {}
    meds = sorted({str(m.get("drug") or "").split(" ")[0] for m in (pc.get("medications") or []) if m.get("drug")})
    comorb = [c for c in (pc.get("comorbidities") or [])][:8]
    screen = [
        f"{(s.get('instrument') or '').split('(')[0].strip()[:24]}={s.get('value')}"
        for s in (pc.get("recent_screening") or [])[-3:]
    ]
    parts = [
        f"PTSD active={ptsd.get('still_active')}, onset age={ptsd.get('age_at_onset')}",
        f"suicide_risk_flagged={pc.get('suicide_risk_flagged')}",
        f"medications: {', '.join(meds) or 'none'}",
        f"comorbidities: {'; '.join(comorb) or 'none'}",
    ]
    if screen:
        parts.append(f"recent screening: {', '.join(screen)}")

    pat = pc.get("pat_screening") or {}
    if pat.get("pcl5_total_score") is not None or pat.get("caps5_severity"):
        parts.append(f"PCL-5={pat.get('pcl5_total_score', '?')}, CAPS-5 severity={pat.get('caps5_severity', '?')}")
    if pat.get("index_trauma_type"):
        parts.append(f"index trauma: {pat['index_trauma_type']}")
    prior = pat.get("prior_trauma_focused_therapy")
    if prior:
        parts.append(f"prior trauma-focused therapy: {prior.get('type', '?')}, outcome: {prior.get('outcome', '?')}")
    if pat.get("flagged_contraindications"):
        parts.append(f"flagged contraindications: {', '.join(pat['flagged_contraindications'])}")

    return "\n".join("- " + p for p in parts)


def _evidence_file(compact_ev: list[dict]) -> str:
    blocks = []
    for e in compact_ev:
        text = " ".join((e.get("text") or "").split())[:_EVIDENCE_TEXT_CAP]
        head = f'[{e.get("evidence_id")}] "{e.get("title")}"'
        if e.get("year"):
            head += f" ({e['year']})"
        blocks.append(f"{head}\n{text}")
    return "\n\n".join(blocks)


def _b64_txt(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _build_message(patient_compact: dict, compact_ev: list[dict]) -> list[dict]:
    """A Manus ContentPart array: short text instructions + two attachments.

    The patient summary is its own patient.txt file, not inline text. An
    earlier inline-text version cost ~19s of wasted runtime per run (~20% of
    total): Manus expected a second attachment, didn't find one, and burned
    several tool calls (find/grep/terminal, some erroring on the sandbox's
    FUSE-mounted paths) hunting for a "patient file" that didn't exist before
    giving up - and sometimes went on to claim no patient data was provided
    at all. Making it a real attachment removes the ambiguity outright.
    """
    text = MANUS_PROMPT.replace("%%N%%", str(len(compact_ev)))
    ev_b64 = _b64_txt(_evidence_file(compact_ev))
    patient_b64 = _b64_txt(_patient_brief(patient_compact))
    return [
        {"type": "text", "text": text},
        {
            "type": "file",
            "file_data": f"data:text/plain;base64,{patient_b64}",
            "filename": "patient.txt",
            "mime_type": "text/plain",
        },
        {
            "type": "file",
            "file_data": f"data:text/plain;base64,{ev_b64}",
            "filename": "evidence.txt",
            "mime_type": "text/plain",
        },
    ]


# --------------------------------------------------------------------------- #
# orchestrator
# --------------------------------------------------------------------------- #

async def run_stream(
    patient: dict, request: Any, cfg: Settings | None = None
) -> AsyncIterator[Event]:
    cfg = cfg or get_settings()
    t0 = perf_counter()
    timings: dict[str, float] = {}

    def mark(name: str, start: float) -> None:
        timings[name] = round(perf_counter() - start, 3)

    # 1 - SAFETY (in code, before any Manus call) --------------------------
    s = perf_counter()
    gate = deterministic_patient_gate(patient)
    patient_compact = compact_patient_view(patient)
    escalate = (not gate["valid"]) or gate["urgent_clinician_review"]
    mark("safety", s)
    yield "stage", {"id": "safety", "state": "done", "gate": gate, "patient_compact": patient_compact}
    if escalate:
        yield "stage", {"id": "safety", "state": "escalated"}
        timings["total"] = round(perf_counter() - t0, 3)
        yield "done", {
            "status": "STOPPED_FOR_CLINICIAN_REVIEW",
            "timings": timings,
            "manus_called": False,
        }
        return

    # 2 - QUERY ----------------------------------------------------------
    s = perf_counter()
    queries = build_fast_queries(patient, cfg)
    mark("query", s)
    yield "stage", {"id": "query", "state": "done", "queries": queries}

    # 3 - RETRIEVE -----------------------------------------------------
    s = perf_counter()
    groups = [search_local_corpus(q, cfg=cfg) for q in queries]
    evidence = _merge_groups(groups, cfg.max_final_evidence)
    retrieved_ids = {e["evidence_id"] for e in evidence}
    compact_ev = compact_evidence(evidence, cfg=cfg)
    mark("retrieve", s)
    yield "stage", {
        "id": "retrieve",
        "state": "done",
        "evidence": [
            {
                "evidence_id": e.get("evidence_id"),
                "title": e.get("title"),
                "file": e.get("file"),
                "page": e.get("page"),
                "text": e.get("text"),
                "raw_bm25": e.get("raw_bm25"),
                "score": e.get("score"),
            }
            for e in evidence
        ],
        "retrieval_meta": {
            "n_local": len(evidence),
            "per_query": [{"query": q, "n": len(g)} for q, g in zip(queries, groups)],
        },
    }
    if not evidence:
        yield "stage", {"id": "synthesis", "state": "skipped"}
        timings["total"] = round(perf_counter() - t0, 3)
        yield "done", {"status": "NO_EVIDENCE_FOUND", "timings": timings, "manus_called": False}
        return

    # 4 - SYNTHESIS (Manus, or offline stub) ----------------------------
    s = perf_counter()
    yield "stage", {"id": "synthesis", "state": "running"}
    task_url: str | None = None

    if not cfg.manus_available:
        yield "manus", {"kind": "offline", "note": "[OFFLINE STUB] Manus was not called."}
        draft = offline_stub(patient_compact, compact_ev)
    else:
        message = _build_message(patient_compact, compact_ev)
        try:
            resp = await manus_client.create_task(
                message, OPTIONS_SCHEMA, cfg.manus_agent_profile, cfg=cfg
            )
        except manus_client.ManusError as exc:
            yield "error", {"message": f"Manus task.create failed: {exc}"}
            return
        task_id = resp["task_id"]
        task_url = resp.get("task_url")
        yield "stage", {"id": "synthesis", "state": "running", "task_id": task_id, "task_url": task_url}

        try:
            async for kind, data in manus_client.stream_task_events(task_id, request, cfg=cfg):
                if kind == "event":
                    yield "manus", {"event": data}
                elif kind == "status":
                    yield "manus_status", {"agent_status": data}
                # "done" -> fall through, handled below
            events = await manus_client.fetch_all_events(task_id, cfg=cfg)
        except manus_client.ManusError as exc:
            yield "error", {"message": f"Manus stream failed: {exc}"}
            return

        raw = manus_client.structured_result(events)
        if raw is None:
            yield "manus", {
                "kind": "warn",
                "note": "structured_output missing; salvaging JSON from the final message",
            }
            try:
                raw = extract_json(manus_client.final_text(events))
            except ValueError:
                raw = None
        draft = _normalize_draft(raw)
        draft["source"] = "manus"

    draft = {**_normalize_draft(draft), "source": draft.get("source", "manus")}
    mark("synthesis", s)
    yield "stage", {"id": "synthesis", "state": "done"}
    yield "draft", draft

    # 5 - AUDIT (deterministic citation check) --------------------------
    s = perf_counter()
    audit = citation_check(draft["recommended_plan"], retrieved_ids)
    audit["evidence_quality"] = evidence_quality_audit(draft["recommended_plan"], compact_ev)
    if audit["audited"] and audit["pass"]:
        status = "READY_FOR_CLINICIAN_REVIEW"
    elif audit["audited"]:
        status = "CITATION_AUDIT_FAILED"
    else:
        status = "SYNTHESIS_EMPTY"
    mark("audit", s)
    yield "citation_audit", {**audit, "status": status}

    timings["total"] = round(perf_counter() - t0, 3)
    yield "done", {
        "status": status,
        "timings": timings,
        "manus_called": cfg.manus_available,
        "task_url": task_url,
    }
