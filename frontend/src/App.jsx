import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { getHealth, logout, onUnauthorized, useRunStream } from "./lib/manus.js";
import Login from "./components/Login.jsx";
import PatientPicker from "./components/PatientPicker.jsx";
import Stepper from "./components/Stepper.jsx";
import Draft from "./components/Draft.jsx";
import DecisionPanel from "./components/DecisionPanel.jsx";
import EvidencePassages from "./components/EvidencePassages.jsx";
import Telemetry from "./components/Telemetry.jsx";

function Atmosphere() {
  // a single delicate vitals trace across the top edge — clinical, quiet
  const trace =
    "M-40,120 L120,120 148,120 158,78 170,150 182,120 250,120 430,120 445,120 456,64 470,120 620,120 " +
    "800,120 815,120 828,96 840,120 980,120 1160,120 1176,120 1188,70 1202,150 1214,120 1480,120";
  return (
    <div className="atmosphere" aria-hidden>
      <svg viewBox="0 0 1440 240" preserveAspectRatio="none">
        <path className="trace" d={trace} />
      </svg>
    </div>
  );
}

const DOT = {
  standby: "neutral",
  working: "ember",
  complete: "teal",
  escalated: "brass",
  error: "rust",
  "connection lost": "rust",
};

function StatusBadge({ label }) {
  return (
    <div className="badge" data-pulse={label === "working" ? "" : undefined}>
      <span className={`badge-dot dot-${DOT[label] || "neutral"}`} />
      {label}
    </div>
  );
}

export default function App() {
  const [health, setHealth] = useState(null);
  const [needsLogin, setNeedsLogin] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [runId, setRunId] = useState(null);
  const [nonce, setNonce] = useState(0);
  const [selectedEv, setSelectedEv] = useState(null);

  useEffect(() => {
    onUnauthorized(() => setNeedsLogin(true));
  }, []);

  useEffect(() => {
    if (needsLogin) return;
    getHealth().then(setHealth).catch(() => setHealth({ error: true }));
  }, [needsLogin]);

  const run = useRunStream(needsLogin ? null : runId, nonce);
  const offline = health ? !health.manus_available : false;

  if (needsLogin) {
    return <Login onSuccess={() => setNeedsLogin(false)} />;
  }

  function startRun(id) {
    setSelectedEv(null);
    setRunId(id);
    setNonce((n) => n + 1);
  }

  function cite(id) {
    setSelectedEv(id);
    if (id) {
      requestAnimationFrame(() =>
        document.getElementById(`ev-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" })
      );
    }
  }

  let statusLabel = "standby";
  if (run.error || run.connectionLost) statusLabel = run.connectionLost ? "connection lost" : "error";
  else if (run.done) statusLabel = run.done.status === "STOPPED_FOR_CLINICIAN_REVIEW" ? "escalated" : "complete";
  else if (run.running) statusLabel = "working";

  const evidence = run.stages.retrieve?.evidence || [];
  const started = Boolean(runId);

  return (
    <div className="shell">
      <Atmosphere />

      {run.done && (
        <div className="print-header print-only">
          <div className="print-header-mark">IASO — Treatment Plan (decision support only)</div>
          <div className="print-header-meta">
            patient {selectedId?.slice(0, 8)} · {run.done.status.replace(/_/g, " ").toLowerCase()} ·
            printed {new Date().toLocaleString()}
          </div>
        </div>
      )}

      <motion.header
        className="masthead no-print"
        initial={{ opacity: 0, y: -14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: [0.2, 0.7, 0.2, 1] }}
      >
        <div className="brand">
          <span className="mark">IASO</span>
          <span className="sub">
            manus console · PTSD evidence synthesis
            {health && (
              <span className="sub-mode">
                {" · "}
                {offline ? "offline (stub)" : `manus · ${health.agent_profile}`}
                {health.index?.chunks ? ` · ${health.index.chunks} chunks` : ""}
              </span>
            )}
          </span>
        </div>
        <div className="mast-right">
          {run.done?.task_url && (
            <a className="task-link" href={run.done.task_url} target="_blank" rel="noreferrer">
              open dossier ↗
            </a>
          )}
          <StatusBadge label={statusLabel} />
          <button
            type="button"
            className="task-link"
            onClick={() => logout().then(() => setNeedsLogin(true))}
          >
            sign out
          </button>
        </div>
      </motion.header>

      <main className="grid grid-iaso">
        <motion.section
          className="panel case"
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.1, ease: [0.2, 0.7, 0.2, 1] }}
        >
          <header className="panel-head no-print">
            <h2>Case</h2>
          </header>
          <div className="panel-scroll">
            <div className="no-print">
              <PatientPicker
                selectedId={selectedId}
                onSelect={setSelectedId}
                onRun={startRun}
                running={run.running}
              />

              {started && <Stepper stages={run.stages} done={run.done} running={run.running} />}
            </div>

            {run.error && <div className="audit-banner" data-tone="bad">{run.error}</div>}
            {run.connectionLost && (
              <div className="audit-banner" data-tone="warn">
                Connection to the run stream dropped. The Manus task may still be running — reload to
                start a fresh run.
              </div>
            )}

            <Draft draft={run.draft} audit={run.citationAudit} onCite={cite} selectedEv={selectedEv} />

            {run.done && (
              <DecisionPanel
                patientId={selectedId}
                status={run.done.status}
                draft={run.draft}
                audit={run.citationAudit}
                evidenceIds={evidence.map((e) => e.evidence_id)}
              />
            )}

            <div className="no-print">
              <EvidencePassages evidence={evidence} selected={selectedEv} onSelect={cite} />
            </div>
          </div>
        </motion.section>

        <div className="no-print">
          <Telemetry
            events={run.manusEvents}
            notes={run.manusNotes}
            status={run.running ? "running" : run.manusStatus}
            offline={offline && started}
          />
        </div>
      </main>
    </div>
  );
}
