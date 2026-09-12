# iaso-manus

An experimental variant of the IASO PTSD pipeline where the **synthesis /
appraisal step runs on the [Manus](https://open.manus.ai) agent API** instead of
a plain LLM call, and you watch Manus work in real time.

Standalone. **Not** part of `iaso-ptsd-agent/` — the deterministic pieces (safety
gate, rule-based query builder, BM25 corpus + retrieval, compact views) are
trimmed ports in `iaso_lite/`, no dependency on the `iaso` package.

## What it does

```
pick a synthetic patient
   │
   ▼
safety gate (in code)  ──► escalate ──► stop, Manus never called
   │
   ▼
rule-based queries  →  local BM25 retrieval  →  N passages, each with an evidence_id
   │
   ▼
ONE Manus task: the passages go in as an attached evidence.txt; Manus appraises
   them and drafts options (structured output). Its working steps stream to the
   Telemetry panel live.
   │
   ▼
deterministic citation check: every option's cited evidence_id must be in the
   retrieved set (set arithmetic — the model never certifies itself)
   │
   ▼
draft + evidence passages + citation banner
```

Retrieval is local and deterministic — Manus only ever sees the passages we
retrieved, never the disk. Decision support only; **no** clinician
accept/amend/reject panel yet (a later pass) — but the safety gate and citation
check are always enforced.

## Run

```bash
cd iaso-manus

# backend  (Python 3.11 — numpy<2.1 has no 3.12+ wheels in this stack)
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # paste MANUS_API_KEY, or leave blank for offline

# frontend
cd frontend && npm install && npm run build && cd ..

# prime the BM25 cache once (~4s for the 54-PDF corpus; cached after)
python -c "from iaso_lite.corpus import get_index; i=get_index(); print(i.n_chunks, 'chunks')"

uvicorn app:app --reload        # http://localhost:8000
```

**Offline mode** — no `MANUS_API_KEY` (or `IASO_MANUS_OFFLINE=1`): the synthesis
step returns a clearly-marked `[OFFLINE STUB]` draft so the whole app, the stepper
and the UI still run end to end. All tests run in this mode.

### Working on the UI

```bash
uvicorn app:app --reload            # :8000 (API)
cd frontend && npm run dev          # :5173, proxies /api → :8000, hot reload
```

## Layout

| path | what |
|---|---|
| `app.py` | FastAPI: `/api/health`, `/api/patients`, `/api/patients/{id}`, `/api/run` (SSE) |
| `iaso_lite/config.py` | env-driven `Settings` (retrieval knobs keep iaso's verbatim defaults) |
| `iaso_lite/corpus.py` · `retrieval.py` · `patient.py` | verbatim ports from `iaso-ptsd-agent/iaso/` |
| `iaso_lite/manus_client.py` | Manus v2 client + the poll/grace event loop (from `manus-chat-test/`) |
| `iaso_lite/prompts.py` | `MANUS_PROMPT` + `OPTIONS_SCHEMA` (Manus structured-output subset) |
| `iaso_lite/synthesis.py` | `run_stream()` orchestrator, `citation_check()`, `offline_stub()` |
| `frontend/src/` | React/Vite/Motion — `App.jsx` shell, `lib/manus.js` (`useRunStream`), `components/{Stepper,Draft,EvidencePassages,PatientPicker,Telemetry}.jsx` |

## SSE event vocabulary (`GET /api/run?patient_id=…`)

| event | payload |
|---|---|
| `stage` | `{id: safety\|query\|retrieve\|synthesis\|audit, state: running\|done\|skipped\|escalated, …}` |
| `manus` | `{event: <raw Manus TaskEvent>}` or `{kind: offline\|warn, note}` |
| `manus_status` | `{agent_status}` |
| `draft` | `{summary, evidence_note, options:[{id,cat,text,why,ev[],cautions[],conf}], missing[], source}` |
| `citation_audit` | `{invalid_evidence_ids[], options_without_evidence_ids[], pass, audited, status}` |
| `done` | `{status, timings, manus_called, task_url?}` |
| `error` | `{message}` |

## Tests

```bash
pytest        # 9 tests, offline, against tests/fixtures/
```

Safety gate escalates the flagged fixture and never reaches retrieval/Manus;
routine profile builds the expected queries and retrieves passages with
`LOCAL-#####` ids; the citation check catches a fabricated id and a
missing-citation option (the "planted error" criterion); `run_stream` emits the
stages in order and the offline stub is clearly marked.

## Notes / limits

- **Manus + long messages.** Manus stashes large inline `message.content` into a
  sandbox file its agent can't read. So the evidence goes in as an *attached*
  `evidence.txt` (base64 `file_data` ContentPart) and the text part stays short.
- **Manus may still browse / ignore instructions.** The prompt forbids it and
  `agent_profile` defaults to `lite`; the real guardrail is the deterministic
  citation check, which rejects any option citing an id that wasn't retrieved →
  `CITATION_AUDIT_FAILED`, offending chips shown struck-through in rust.
- **Corpus quality.** The 54-PDF corpus is neuroscience/imaging-heavy and thin on
  treatment RCTs, so Manus often (correctly) returns "insufficient evidence" →
  `SYNTHESIS_EMPTY` rather than fabricating options. That's the retrieval gap the
  IASO team already documents, not a bug here.
- **`/api/run` creates a Manus task per connection** and is not idempotent. On a
  dropped stream the client stops (no auto-retry) rather than spawn a second
  task; reload to start fresh. Synthesis takes ~20–60s.
- No run persistence; single operator; no auth.
