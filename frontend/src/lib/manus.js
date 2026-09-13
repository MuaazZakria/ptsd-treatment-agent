import { useEffect, useState } from "react";
import { EventSourcePolyfill } from "event-source-polyfill";

/* ---- REST -------------------------------------------------------------- */

// Set VITE_API_BASE_URL (e.g. to an ngrok URL) when the frontend is deployed
// separately from the backend (e.g. Vercel frontend + tunnelled FastAPI).
// Left empty, requests stay relative and same-origin, as before.
const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

// Free ngrok tunnels show an HTML interstitial to browser-like requests
// unless this header is present; harmless when not on ngrok.
const SKIP_NGROK_WARNING = { "ngrok-skip-browser-warning": "true" };

const asJson = (r) => r.json().then((b) => ({ ok: r.ok, status: r.status, body: b }));

// A 401 from any /api/* call (session missing/expired) is handled in one
// place rather than special-cased in every component. App.jsx registers the
// "show the login screen" callback here.
let unauthorizedHandler = null;
export function onUnauthorized(fn) {
  unauthorizedHandler = fn;
}

async function apiFetch(path, init) {
  const r = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: { ...SKIP_NGROK_WARNING, ...init?.headers },
  });
  if (r.status === 401) unauthorizedHandler?.();
  return r;
}

function fmtErr(body) {
  const d = body?.detail ?? body;
  return typeof d === "string" ? d : JSON.stringify(d);
}

export async function getHealth() {
  const { body } = await apiFetch("/api/health").then(asJson);
  return body;
}

export async function login(password) {
  const { ok, body } = await apiFetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  }).then(asJson);
  if (!ok) throw new Error(fmtErr(body));
  return body; // { ok, auth_enabled }
}

export async function logout() {
  await apiFetch("/api/logout", { method: "POST" });
}

export async function listPatients({ q = "", flagged = false } = {}) {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (flagged) params.set("flagged", "true");
  const { ok, body } = await apiFetch(`/api/patients?${params}`).then(asJson);
  if (!ok) throw new Error(fmtErr(body));
  return body; // { total, returned, patients: [row] }
}

export async function getPatient(id) {
  const { ok, body } = await apiFetch(`/api/patients/${encodeURIComponent(id)}`).then(asJson);
  if (!ok) throw new Error(fmtErr(body));
  return body; // { profile, compact }
}

export async function postDecision(payload) {
  const { ok, body } = await apiFetch("/api/decision", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).then(asJson);
  if (!ok) throw new Error(fmtErr(body));
  return body; // the recorded decision
}

export async function getDecisions(limit = 200) {
  const { ok, body } = await apiFetch(`/api/decisions?limit=${limit}`).then(asJson);
  if (!ok) throw new Error(fmtErr(body));
  return body.decisions;
}

/* ---- shared Manus-event helpers (from manus-chat-test) ---------------- */

export const payloadOf = (e) => (e && typeof e[e.type] === "object" && e[e.type]) || e || {};

export const tsMs = (e) => {
  const n = Number(e?.timestamp);
  if (Number.isFinite(n) && n > 0) return n;
  const p = Date.parse(e?.created_at ?? "");
  return Number.isNaN(p) ? null : p;
};

export const CHAT_TYPES = new Set([
  "assistant_message",
  "user_message",
  "error_message",
  "structured_output_result",
]);

/* ---- the run stream -------------------------------------------------- */

const STAGE_IDS = ["safety", "query", "retrieve", "synthesis", "audit"];

const blank = () => ({
  running: false,
  stages: {},
  manusEvents: [],
  manusNotes: [],
  manusStatus: "idle",
  draft: null,
  citationAudit: null,
  done: null,
  error: null,
  connectionLost: false,
});

/**
 * One EventSource against GET /api/run?patient_id=…. Assembles the IASO stage
 * payloads plus the live Manus working feed. `nonce` forces a fresh run.
 *
 * NOTE: /api/run creates a Manus task per connection. On a dropped connection
 * we close (no auto-retry) rather than spawn a second task.
 */
export function useRunStream(patientId, nonce) {
  const [state, setState] = useState(blank);

  useEffect(() => {
    if (!patientId) return;
    setState({ ...blank(), running: true });

    const store = new Map();
    let seq = 0;
    const es = new EventSourcePolyfill(
      `${API_BASE}/api/run?patient_id=${encodeURIComponent(patientId)}`,
      { withCredentials: true, headers: SKIP_NGROK_WARNING }
    );
    const patch = (fn) => setState((s) => ({ ...s, ...fn(s) }));

    es.addEventListener("stage", (e) => {
      const p = JSON.parse(e.data);
      patch((s) => ({
        stages: { ...s.stages, [p.id]: { ...(s.stages[p.id] || {}), ...p } },
      }));
    });

    es.addEventListener("manus", (e) => {
      const p = JSON.parse(e.data);
      if (p.event) {
        const ev = p.event;
        const id = String(ev.id ?? `${ev.type}:${ev.timestamp}`);
        const prev = store.get(id);
        store.set(id, { ...ev, _id: id, _seq: prev ? prev._seq : seq++ });
        const sorted = [...store.values()].sort(
          (a, b) => (tsMs(a) ?? 0) - (tsMs(b) ?? 0) || a._seq - b._seq
        );
        patch(() => ({ manusEvents: sorted }));
      } else {
        patch((s) => ({ manusNotes: [...s.manusNotes, p] }));
      }
    });

    es.addEventListener("manus_status", (e) =>
      patch(() => ({ manusStatus: JSON.parse(e.data).agent_status }))
    );
    es.addEventListener("draft", (e) => patch(() => ({ draft: JSON.parse(e.data) })));
    es.addEventListener("citation_audit", (e) =>
      patch(() => ({ citationAudit: JSON.parse(e.data) }))
    );
    es.addEventListener("done", (e) => {
      patch(() => ({ done: JSON.parse(e.data), running: false }));
      es.close();
    });
    es.addEventListener("error", (e) => {
      try {
        patch(() => ({ error: JSON.parse(e.data).message, running: false }));
      } catch {
        /* not a server 'error' event */
      }
      es.close();
    });
    es.onerror = () => {
      setState((s) =>
        s.done || s.error ? s : { ...s, running: false, connectionLost: true }
      );
      es.close();
    };

    return () => es.close();
  }, [patientId, nonce]);

  return { ...state, STAGE_IDS };
}
