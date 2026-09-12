"""
Patient loading, the deterministic safety gate, and the compact views sent to
the model.

Verbatim port of iaso-ptsd-agent/iaso/patient.py (minus the decisions helpers).
The safety gate is intentionally small and deterministic: a positive
suicide-risk flag or a missing required field stops automated synthesis before
Manus is ever called. The thresholds here are NOT clinically validated.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from .config import Settings, get_settings

REQUIRED_FIELDS = ("patient_id", "ptsd", "treatment")


def deterministic_patient_gate(patient: dict[str, Any]) -> dict[str, Any]:
    missing = [k for k in REQUIRED_FIELDS if k not in patient]
    return {
        "valid": not missing,
        "missing_required_fields": missing,
        "urgent_clinician_review": patient.get("suicide_risk_flagged") is True,
        "note": "A false/absent suicide-risk flag does not establish absence of current risk.",
    }


def _compact_pat_screening(pat: dict[str, Any] | None) -> dict[str, Any] | None:
    """Trims the optional `pat_screening` overlay (present on some patient
    files, e.g. a PCL-5/CAPS-5 + treatment-history overlay) down to the
    fields that matter for drafting *any* treatment plan, not just a
    psychedelic-assisted-therapy one: symptom severity, whether a prior
    trauma-focused therapy was tried and how it went, and any flagged
    contraindication. Absent on patient files that don't carry this overlay -
    every caller must handle None."""
    if not isinstance(pat, dict):
        return None
    hist = (pat.get("treatment_history") or {}).get("prior_trauma_focused_therapy") or {}
    trauma = pat.get("trauma_profile") or {}
    contraindications = {k: v for k, v in (pat.get("contraindications") or {}).items() if v}
    out = {
        "pcl5_total_score": pat.get("pcl5_total_score"),
        "caps5_severity": pat.get("caps5_severity"),
        "index_trauma_type": trauma.get("index_trauma_type"),
        "prior_trauma_focused_therapy": (
            {"type": hist.get("type"), "outcome": hist.get("outcome")} if hist.get("attempted") else None
        ),
        "flagged_contraindications": list(contraindications) or None,
    }
    return {k: v for k, v in out.items() if v is not None}


def compact_patient_view(patient: dict[str, Any]) -> dict[str, Any]:
    tx = patient.get("treatment", {}) or {}
    screening = patient.get("screening_scores", [])
    if isinstance(screening, list):
        screening = screening[-4:]
    return {
        "patient_id": patient.get("patient_id"),
        "ptsd": patient.get("ptsd", {}),
        "comorbidities": (patient.get("comorbidities_at_onset") or [])[:12],
        "suicide_risk_flagged": patient.get("suicide_risk_flagged"),
        "medications": [
            {"drug": m.get("drug"), "start": m.get("start")}
            for m in (tx.get("medications") or [])[-5:]
        ],
        "care_plans": (tx.get("care_plans") or [])[:4],
        "recent_screening": screening,
        "pat_screening": _compact_pat_screening(patient.get("pat_screening")),
    }


def compact_evidence(
    evidence: list[dict[str, Any]],
    *,
    max_items: int | None = None,
    max_chars: int | None = None,
    cfg: Settings | None = None,
) -> list[dict[str, Any]]:
    cfg = cfg or get_settings()
    max_items = max_items or cfg.max_final_evidence
    max_chars = max_chars or cfg.evidence_chars
    return [
        {
            "evidence_id": e.get("evidence_id"),
            "src": e.get("source"),
            "title": (e.get("title") or "")[:110],
            "year": e.get("year", ""),
            "text": (e.get("text") or "")[:max_chars],
        }
        for e in evidence[:max_items]
    ]


# --------------------------------------------------------------------------- #
# dataset
# --------------------------------------------------------------------------- #

@lru_cache(maxsize=1)
def load_patients(cfg: Settings | None = None) -> list[dict[str, Any]]:
    cfg = cfg or get_settings()
    if not cfg.patients_file.exists():
        raise FileNotFoundError(
            f"No patient file at {cfg.patients_file}. Set IASO_PATIENTS_FILE to the "
            "synthetic Synthea JSON (ptsd_veteran_US_profiles.json)."
        )
    data = json.loads(cfg.patients_file.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = [data]
    return data


def patient_by_id(patient_id: str, cfg: Settings | None = None) -> dict[str, Any] | None:
    for p in load_patients(cfg):
        if str(p.get("patient_id")) == str(patient_id):
            return p
    return None


def patient_summary_row(patient: dict[str, Any]) -> dict[str, Any]:
    """One compact record for the patient picker."""
    dem = patient.get("demographics", {}) or {}
    ptsd = patient.get("ptsd", {}) or {}
    tx = patient.get("treatment", {}) or {}
    return {
        "patient_id": patient.get("patient_id"),
        "gender": dem.get("gender"),
        "age_at_onset": ptsd.get("age_at_onset"),
        "state": dem.get("state"),
        "ptsd_active": ptsd.get("still_active"),
        "suicide_risk_flagged": bool(patient.get("suicide_risk_flagged")),
        "n_comorbidities": len(patient.get("comorbidities_at_onset") or []),
        "n_medications": len(tx.get("medications") or []),
        "medications": [m.get("drug") for m in (tx.get("medications") or [])][:6],
    }
