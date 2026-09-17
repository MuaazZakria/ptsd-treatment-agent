"""
Clinician review records.

Every decision is written as
its own audit file under decisions/<patient_id>/ *and* appended to
decisions/log.jsonl, so the log survives a restart and one bad write doesn't
lose the rest of the history.

The client sends the draft/audit it is deciding on (this app has no
server-side run cache in this pass) so the record is self-contained: what was drafted, what
the citation check found, and what the clinician decided about it.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .config import Settings, get_settings

# approve/amend/reject: a draft exists (READY_FOR_CLINICIAN_REVIEW,
# CITATION_AUDIT_FAILED, SYNTHESIS_EMPTY) and the clinician is reacting to it.
# acknowledge/escalate: no draft to react to (STOPPED_FOR_CLINICIAN_REVIEW,
# NO_EVIDENCE_FOUND) - there's still an audit trail of how the case was handled.
VALID_DECISIONS = ("approve", "amend", "reject", "acknowledge", "escalate")

REVIEW_DECISIONS = ("approve", "amend", "reject")
ACKNOWLEDGE_DECISIONS = ("acknowledge", "escalate")


def record_decision(
    *,
    patient_id: str,
    clinician: str,
    decision: str,
    notes: str = "",
    status: str | None = None,
    draft: dict[str, Any] | None = None,
    citation_audit: dict[str, Any] | None = None,
    evidence_ids: list[str] | None = None,
    cfg: Settings | None = None,
) -> dict[str, Any]:
    cfg = cfg or get_settings()
    clinician = (clinician or "").strip()
    decision = (decision or "").strip().lower()
    if not clinician:
        raise ValueError("clinician name is required")
    if decision not in VALID_DECISIONS:
        raise ValueError(f"decision must be one of {VALID_DECISIONS}, got {decision!r}")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record = {
        "decision_id": uuid.uuid4().hex[:8],
        "recorded_at": now,
        "patient_id": str(patient_id or "unknown"),
        "clinician": clinician,
        "decision": decision,
        "notes": (notes or "").strip(),
        "pipeline_status": status,
        "citation_audit": citation_audit,
        "draft": draft,
        "evidence_ids": evidence_ids or [],
    }

    patient_dir = cfg.decisions_dir / record["patient_id"]
    patient_dir.mkdir(parents=True, exist_ok=True)
    audit_path = patient_dir / f"decision_{record['decision_id']}.json"
    audit_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    log_path = cfg.decisions_dir / "log.jsonl"
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    record["audit_file"] = str(audit_path.relative_to(cfg.decisions_dir))
    return record


def read_log(cfg: Settings | None = None, *, limit: int = 200) -> list[dict[str, Any]]:
    cfg = cfg or get_settings()
    log_path = cfg.decisions_dir / "log.jsonl"
    if not log_path.exists():
        return []
    rows = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return rows[-limit:][::-1]
