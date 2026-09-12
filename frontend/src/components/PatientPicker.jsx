import { useEffect, useRef, useState } from "react";
import { listPatients } from "../lib/manus.js";

export default function PatientPicker({ selectedId, onSelect, onRun, running }) {
  const [q, setQ] = useState("");
  const [flagged, setFlagged] = useState(false);
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const debounce = useRef();

  useEffect(() => {
    clearTimeout(debounce.current);
    debounce.current = setTimeout(() => {
      listPatients({ q, flagged })
        .then((d) => {
          setData(d);
          setErr(null);
        })
        .catch((e) => setErr(e.message));
    }, 200);
    return () => clearTimeout(debounce.current);
  }, [q, flagged]);

  const selected = data?.patients.find((p) => p.patient_id === selectedId);

  return (
    <section className="picker">
      <div className="picker-controls">
        <input
          className="picker-search"
          placeholder="search id · medication · state"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <label className="picker-flag">
          <input
            type="checkbox"
            checked={flagged}
            onChange={(e) => setFlagged(e.target.checked)}
          />
          suicide-risk flagged only
        </label>
      </div>

      {err && <p className="picker-err">{err}</p>}
      {data && (
        <p className="picker-count">
          {data.returned} of {data.total} synthetic patients
        </p>
      )}

      <ul className="picker-list">
        {(data?.patients || []).map((p) => (
          <li key={p.patient_id}>
            <button
              type="button"
              className={`picker-row${p.patient_id === selectedId ? " sel" : ""}`}
              onClick={() => onSelect(p.patient_id)}
            >
              <span className="picker-row-id">{p.patient_id.slice(0, 8)}</span>
              <span className="picker-row-sub">
                {p.gender} · onset {p.age_at_onset} · {p.n_comorbidities} comorbid ·{" "}
                {p.medications.filter(Boolean).map(drugName).join(", ") || "no meds"}
              </span>
              {p.suicide_risk_flagged && <span className="picker-row-flag">flagged</span>}
            </button>
          </li>
        ))}
      </ul>

      <button
        type="button"
        className="run-btn"
        disabled={!selectedId || running}
        onClick={() => onRun(selectedId)}
      >
        {running ? "running…" : "run case"} <span className="arrow">→</span>
      </button>
      {selected?.suicide_risk_flagged && (
        <p className="picker-hint">This profile will stop at the safety gate — no Manus call.</p>
      )}
    </section>
  );
}

function drugName(s) {
  return String(s).split(/\s+\d/)[0].trim() || String(s);
}
