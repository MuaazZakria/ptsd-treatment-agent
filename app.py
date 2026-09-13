"""
iaso-manus - IASO PTSD pipeline with the synthesis step on the Manus agent API.

Standalone experimental app. NOT part of iaso-ptsd-agent/. Retrieval is local and
deterministic; only the retrieved passages go to Manus; the safety gate and the
citation check run in code.

  POST /api/login                 - admin password -> session cookie
  POST /api/logout                - clear the session cookie
  GET  /api/health                - config + evidence index stats
  GET  /api/patients?q=&flagged=  - synthetic patient picker rows
  GET  /api/patients/{id}         - full profile + compact view
  GET  /api/run?patient_id=       - SSE: IASO stages + live Manus working + draft
  POST /api/decision              - record a clinician's approve/amend/reject
  GET  /api/decisions             - the persisted decision log

Every /api/* route except /api/login requires a session cookie once
IASO_ADMIN_PASSWORD is set (see iaso_lite/auth.py). With no password
configured the app runs open (a startup warning is printed).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from iaso_lite import auth, decisions
from iaso_lite.config import get_settings
from iaso_lite.corpus import get_index
from iaso_lite.patient import load_patients, patient_by_id, patient_summary_row
from iaso_lite.synthesis import run_stream

STEPS = [
    ("safety", "Safety gate"),
    ("query", "Clinical questions"),
    ("retrieve", "Evidence retrieval"),
    ("synthesis", "Appraisal + options (Manus)"),
    ("audit", "Citation check"),
]

app = FastAPI(title="iaso-manus", version="0.1.0")

_cors_origins = get_settings().cors_origins
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(_cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.on_event("startup")
async def _warm_index() -> None:
    # build the BM25 cache off the request path (best effort)
    try:
        await asyncio.to_thread(get_index, get_settings())
    except Exception as exc:  # missing corpus etc. - surfaced by /api/health
        print(f"[startup] evidence index not ready: {exc}")


def require_admin(iaso_session: str | None = Cookie(default=None)) -> None:
    cfg = get_settings()
    if not cfg.auth_enabled:
        return  # no IASO_ADMIN_PASSWORD configured - running open, see the startup warning
    if not auth.verify_token(iaso_session, cfg):
        raise HTTPException(401, "Not signed in.")


class LoginRequest(BaseModel):
    password: str


@app.post("/api/login")
def login(req: LoginRequest, response: Response) -> dict[str, Any]:
    cfg = get_settings()
    if not cfg.auth_enabled:
        return {"ok": True, "auth_enabled": False}
    if not auth.check_password(req.password, cfg):
        raise HTTPException(401, "Wrong password.")
    token = auth.issue_token(cfg)
    cross_site = bool(cfg.cors_origins)  # frontend on a different origin (e.g. Vercel)
    response.set_cookie(
        auth.COOKIE_NAME,
        token,
        max_age=auth.SESSION_TTL_S,
        httponly=True,
        samesite="none" if cross_site else "lax",
        secure=cross_site,  # SameSite=None requires Secure; ngrok/Vercel are both https
    )
    return {"ok": True, "auth_enabled": True}


@app.post("/api/logout")
def logout(response: Response) -> dict[str, Any]:
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


@app.get("/api/health")
def health() -> dict[str, Any]:
    cfg = get_settings()
    out: dict[str, Any] = {
        "manus_available": cfg.manus_available,
        "offline": not cfg.manus_available,
        "agent_profile": cfg.manus_agent_profile,
        "auth_enabled": cfg.auth_enabled,
        "steps": [{"key": k, "label": lbl} for k, lbl in STEPS],
    }
    try:
        idx = get_index(cfg)
        out["index"] = {
            "documents": idx.n_documents,
            "chunks": idx.n_chunks,
            "from_cache": idx.from_cache,
            "source_dir": str(idx.source_dir),
        }
    except Exception as exc:
        out["index"] = {"error": str(exc)}
    return out


@app.get("/api/patients", dependencies=[Depends(require_admin)])
def list_patients(
    limit: int | None = None, q: str | None = None, flagged: bool = False
) -> dict[str, Any]:
    cfg = get_settings()
    rows = [patient_summary_row(p) for p in load_patients(cfg)]
    if flagged:
        rows = [r for r in rows if r["suicide_risk_flagged"]]
    if q:
        needle = q.lower().strip()
        rows = [
            r
            for r in rows
            if needle in str(r["patient_id"]).lower()
            or needle in " ".join(str(m or "") for m in r["medications"]).lower()
            or needle in str(r["state"] or "").lower()
        ]
    total = len(rows)
    rows = rows[: (limit or cfg.demo_patient_limit)]
    return {"total": total, "returned": len(rows), "patients": rows}


@app.get(
    "/api/patients/{patient_id}", dependencies=[Depends(require_admin)]
)
def get_patient(patient_id: str) -> dict[str, Any]:
    from iaso_lite.patient import compact_patient_view

    p = patient_by_id(patient_id, get_settings())
    if p is None:
        raise HTTPException(404, f"No patient {patient_id!r}")
    return {"profile": p, "compact": compact_patient_view(p)}


def _sse(event: str, data: Any) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n".encode()


@app.get("/api/run", dependencies=[Depends(require_admin)])
async def run(request: Request, patient_id: str) -> StreamingResponse:
    cfg = get_settings()
    patient = patient_by_id(patient_id, cfg)
    if patient is None:
        raise HTTPException(404, f"No patient {patient_id!r}")

    async def gen():
        yield _sse("start", {"patient_id": patient_id})
        try:
            async for name, payload in run_stream(patient, request, cfg):
                yield _sse(name, payload)
        except Exception as exc:  # noqa: BLE001 - surface anything to the client
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class DecisionRequest(BaseModel):
    patient_id: str
    clinician: str
    decision: str  # approve | amend | reject | acknowledge | escalate
    notes: str = ""
    status: str | None = None
    draft: dict[str, Any] | None = None
    citation_audit: dict[str, Any] | None = None
    evidence_ids: list[str] = []


@app.post("/api/decision", dependencies=[Depends(require_admin)])
def record_decision(req: DecisionRequest) -> dict[str, Any]:
    try:
        return decisions.record_decision(
            patient_id=req.patient_id,
            clinician=req.clinician,
            decision=req.decision,
            notes=req.notes,
            status=req.status,
            draft=req.draft,
            citation_audit=req.citation_audit,
            evidence_ids=req.evidence_ids,
            cfg=get_settings(),
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/decisions", dependencies=[Depends(require_admin)])
def list_decisions(limit: int = 200) -> dict[str, Any]:
    return {"decisions": decisions.read_log(get_settings(), limit=limit)}


_STATIC = Path(__file__).parent / "static"
if _STATIC.is_dir():
    app.mount("/", StaticFiles(directory=str(_STATIC), html=True), name="static")
else:  # frontend not built yet
    @app.get("/")
    def _no_build() -> dict[str, str]:
        return {"detail": "Frontend not built. Run: cd frontend && npm install && npm run build"}
