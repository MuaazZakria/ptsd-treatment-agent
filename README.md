# IASO Manus Console

A clinician-facing PTSD treatment-evidence synthesis tool. Pick a synthetic
patient, and the app retrieves relevant published evidence, hands it to a
[Manus](https://open.manus.ai) agent to draft a clinical-note-style treatment
plan, and runs a deterministic citation check on the result before a
clinician reviews it — accept, amend, or reject. Nothing here diagnoses or
prescribes; every output is decision support for a human to sign off on.

```
pick a synthetic patient
   │
   ▼
safety gate (deterministic code)  ──►  flagged/invalid ──► stop, Manus never called
   │
   ▼
rule-based queries  →  local BM25 retrieval  →  up to 5 passages, each an evidence_id
   │
   ▼
ONE Manus task: patient summary + evidence passages go in as attached files;
   Manus drafts a plan (structured output). Its working steps stream live.
   │
   ▼
deterministic citation enforcement: any citation that isn't in the retrieved
   set is stripped; any plan item left with no valid citation is dropped
   (never fabricated, never silently discarded — shown for the record)
   │
   ▼
draft + evidence passages + clinician decision panel (accept / amend / reject)
   → recorded to an append-only decision log
```

Retrieval is local and fully deterministic — Manus only ever sees the
passages this app retrieved, never the corpus or filesystem directly.

Standalone project. **Not** part of `iaso-ptsd-agent/` — the deterministic
pieces (safety gate, query builder, BM25 corpus, compact patient views) are
self-contained ports in `iaso_lite/`, no shared dependency.

## Requirements

- Python 3.11 (`numpy<2.1` in this stack has no 3.12+ wheels)
- Node.js 18+ / npm
- A [Manus](https://open.manus.ai) API key — optional, see **Offline mode** below

## Setup

```bash
git clone <this repo> && cd iaso-manus

# --- backend ---
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

| Variable | What it's for |
|---|---|
| `MANUS_API_KEY` | Your Manus API key. Leave blank to run offline (deterministic stub instead of a real synthesis). |
| `IASO_EVIDENCE_DIR` | Folder of `.pdf`/`.txt` evidence documents for BM25 retrieval. |
| `IASO_PATIENTS_FILE` | JSON file: an array of patient records (see **Data** below for the required shape). |
| `IASO_ADMIN_PASSWORD` | Required to gate the app behind a login screen. Leave blank to run fully open (local/offline dev only — a startup warning is printed). |
| `IASO_SESSION_SECRET` | Optional; pins the session-signing key so logins survive a restart. Leave blank to auto-generate one per process (safer default — every session invalidates on restart). |
| `IASO_DECISIONS_DIR` | Where clinician decisions are logged (JSONL + per-decision JSON snapshots). |

See `.env.example` for the full list, including retrieval-tuning knobs
(chunk size, top-k, BM25 threshold) that default to sane values and rarely
need changing.

```bash
# --- frontend ---
cd frontend
npm install
npm run build          # produces ../static/, served by the backend
cd ..
```

## Running it

**Single process (production-style):**

```bash
source .venv/bin/activate
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` — this serves the built frontend from `static/`
directly off the same FastAPI app.

**Frontend + backend separately (for UI development, hot reload):**

```bash
# terminal 1 — backend
source .venv/bin/activate
uvicorn app:app --reload --port 8000

# terminal 2 — frontend dev server
cd frontend
npm run dev             # http://localhost:5173, proxies /api → :8000
```

Use `http://localhost:5173` while developing the UI; rebuild with
`npm run build` before serving through the backend alone again.

### Offline mode

No `MANUS_API_KEY` (or `IASO_MANUS_OFFLINE=1`): the synthesis step returns a
clearly-marked `[OFFLINE STUB]` draft instead of calling Manus, so the whole
pipeline and UI run end to end for development. All tests run this way —
no API key is required to develop or test this project.

## Data

**Patients** (`IASO_PATIENTS_FILE`) — a JSON array. Each record needs at
minimum:
```json
{
  "patient_id": "...",
  "ptsd": { "still_active": true, "age_at_onset": 40 },
  "treatment": { "medications": [{ "drug": "...", "start": "..." }] }
}
```
Optional fields the pipeline also uses when present: `comorbidities_at_onset`,
`suicide_risk_flagged`, `screening_scores`, and a `pat_screening` overlay
(`pcl5_total_score`, `caps5_severity`, `trauma_profile`, `treatment_history`,
`contraindications`) for richer, patient-specific drafting.

**Evidence corpus** (`IASO_EVIDENCE_DIR`) — any folder of `.pdf` or `.txt`
files. Dropping a file in or removing one automatically invalidates the BM25
disk cache (`IASO_CACHE_DIR`) on next load — no manual rebuild step. Evidence
quality matters a lot here: retrieval is only as good as what's in this
folder relative to the kinds of treatment questions the query builder asks
(see `iaso_lite/retrieval.py::build_fast_queries`).

## Layout

| path | what |
|---|---|
| `app.py` | FastAPI: auth, `/api/patients`, `/api/run` (SSE), `/api/decision`, `/api/decisions` |
| `iaso_lite/config.py` | env-driven `Settings` |
| `iaso_lite/patient.py` | patient loading, safety gate, compact views sent to the model |
| `iaso_lite/corpus.py` / `retrieval.py` | PDF/txt → BM25 index; rule-based query builder |
| `iaso_lite/manus_client.py` | Manus v2 client + task polling/streaming |
| `iaso_lite/prompts.py` | the Manus prompt + structured-output schema |
| `iaso_lite/synthesis.py` | `run_stream()` orchestrator, citation enforcement, offline stub |
| `iaso_lite/auth.py` | stdlib-only HMAC session tokens (no external auth dependency) |
| `iaso_lite/decisions.py` | append-only decision log + per-decision snapshots |
| `frontend/src/App.jsx` | shell: login gate, patient picker, run stream, decision panel |
| `frontend/src/components/` | `Login`, `Draft`, `DecisionPanel`, `EvidencePassages`, `Stepper`, `Telemetry` |
| `frontend/src/lib/manus.js` | REST calls + `useRunStream` SSE hook |

## SSE event vocabulary (`GET /api/run?patient_id=…`)

| event | payload |
|---|---|
| `stage` | `{id: safety\|query\|retrieve\|synthesis\|audit, state, …}` |
| `manus` | raw Manus task events (working steps, tool calls) |
| `manus_status` | `{agent_status}` |
| `draft` | `{assessment, recommended_plan[], monitoring[], reassessment_triggers[], missing[], source}` |
| `citation_audit` | `{invalid_evidence_ids[], options_without_evidence_ids[], dropped_items[], evidence_quality, pass, audited, status}` |
| `done` | `{status, timings, manus_called, task_url?}` |
| `error` | `{message}` |

`status` is one of `READY_FOR_CLINICIAN_REVIEW`, `SYNTHESIS_EMPTY`,
`STOPPED_FOR_CLINICIAN_REVIEW` (safety gate), or `CITATION_AUDIT_FAILED`
(structurally rare — see **Guardrails** below).

## Auth & decisions

The whole app sits behind a single shared admin password
(`IASO_ADMIN_PASSWORD`) — a stdlib-only HMAC-signed session cookie, no
external auth dependency. This is an access gate for a single-operator tool,
not real multi-user identity management.

Once a case reaches a draft, the clinician records **accept / accept with
amendments / reject** (or, if the case never reached a draft,
**acknowledge / escalate**) with their name and notes. Each decision is
written to `IASO_DECISIONS_DIR` as an append-only JSONL log line plus a full
per-decision JSON snapshot (draft, citation audit, evidence ids at the time)
— so the historical record doesn't change if the corpus is updated later.

## Guardrails

- **Safety gate** — a missing required patient field or a positive
  `suicide_risk_flagged` stops the pipeline before Manus is ever called.
- **Citation enforcement** — any citation Manus produces that isn't in the
  actually-retrieved evidence set is stripped; a plan item left with no
  valid citation is dropped entirely rather than shown broken. Dropped items
  aren't silently discarded — they're returned in `dropped_items` and shown
  in the UI so nothing disappears from the record.
- **Evidence-quality check** — a plan item claiming high/moderate confidence
  from only mechanistic/animal-model evidence is flagged (warn-only; never
  changes the model's stated confidence, just surfaces the discrepancy).

None of this makes Manus's output deterministic or guaranteed-correct — it
guarantees that whatever it produces has been checked against the same fixed
rules every time, and nothing unverifiable reaches the clinician labeled as
if it were real evidence.

## Tests

```bash
source .venv/bin/activate
pytest -q
```

29 tests, fully offline (no API key needed): safety-gate behavior, query
building per medication/comorbidity branch, citation-check and
citation-enforcement logic, decision persistence, and auth.

## Printing / exporting a plan

Once a decision is recorded, a "print / save as pdf" control appears next to
it. This uses the browser's native print dialog against a dedicated print
stylesheet (no server-side PDF rendering, no added dependency) — pick "Save
as PDF" in the print dialog to export.

## Known limitations

- Single shared admin password, not real multi-user IAM.
- No run history / reopening past runs — one draft per run, re-run to review
  a case again.
- `/api/run` starts a new Manus task per connection and isn't idempotent; a
  dropped stream doesn't auto-retry.
- Local file storage only — no database, no multi-tenant isolation.
- Not validated against real clinical outcomes; this is a decision-support
  architecture prototype, not a clinically validated product.
