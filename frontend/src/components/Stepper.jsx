import { motion } from "motion/react";

const LABELS = {
  safety: "Safety gate",
  query: "Clinical questions",
  retrieve: "Evidence retrieval",
  synthesis: "Appraisal + options · Manus",
  audit: "Citation check",
};

const ORDER = ["safety", "query", "retrieve", "synthesis", "audit"];

function stepState(id, stages, running) {
  const s = stages[id];
  if (!s) return running ? "pending" : "pending";
  if (s.state === "escalated") return "escalated";
  if (s.state === "skipped") return "skipped";
  if (s.state === "done") return "done";
  if (s.state === "running") return "active";
  return "pending";
}

const GLYPH = { done: "✓", escalated: "!", skipped: "–", error: "✕" };

export default function Stepper({ stages, done, running }) {
  const timings = done?.timings || {};
  return (
    <ol className="stepper">
      {ORDER.map((id, i) => {
        const st = stepState(id, stages, running);
        const s = stages[id] || {};
        const secs = timings[id];
        return (
          <motion.li
            key={id}
            className="step"
            data-state={st}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.05, duration: 0.35 }}
          >
            <span className="step-dot" data-state={st}>
              {st === "active" ? <span className="step-spin" /> : GLYPH[st] || i + 1}
            </span>
            <div className="step-body">
              <div className="step-title">
                {LABELS[id]}
                {secs != null && <span className="step-secs">{secs.toFixed(2)}s</span>}
              </div>
              {id === "query" && s.queries && (
                <ul className="step-notes">
                  {s.queries.map((q, k) => (
                    <li key={k}>{q}</li>
                  ))}
                </ul>
              )}
              {id === "retrieve" && s.retrieval_meta && (
                <div className="step-notes">
                  {s.retrieval_meta.n_local} passage{s.retrieval_meta.n_local === 1 ? "" : "s"} from the local corpus
                </div>
              )}
              {id === "safety" && st === "escalated" && (
                <div className="step-notes step-notes--warn">
                  escalated by the deterministic gate — Manus was not called
                </div>
              )}
              {id === "synthesis" && s.task_url && (
                <a className="step-link" href={s.task_url} target="_blank" rel="noreferrer">
                  open dossier ↗
                </a>
              )}
            </div>
          </motion.li>
        );
      })}
      {done && (
        <li className="step step-total">
          <span className="step-dot" data-state="done">
            Σ
          </span>
          <div className="step-body">
            <div className="step-title">
              {done.status.replace(/_/g, " ").toLowerCase()}
              {timings.total != null && <span className="step-secs">{timings.total.toFixed(2)}s total</span>}
            </div>
          </div>
        </li>
      )}
    </ol>
  );
}
