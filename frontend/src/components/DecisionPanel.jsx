import { useRef, useState } from "react";
import { postDecision } from "../lib/manus.js";

const LABEL = {
  approve: "Accepted",
  amend: "Accepted with amendments",
  reject: "Rejected",
  acknowledge: "Reviewed and handled",
  escalate: "Escalated",
};

// Two modes: a draft exists to react to ("review"), or the pipeline stopped
// before drafting anything ("acknowledge") — safety escalation or no evidence.
const MODES = {
  review: {
    heading: "Clinician decision",
    lead: "This is what the record will reflect. Nothing here is actioned automatically.",
    submit: "Record decision",
    options: [
      ["approve", "Accept", "the draft is sound as written"],
      ["amend", "Accept with amendments", "note your changes below"],
      ["reject", "Reject", "there's a problem a revision won't fix"],
    ],
    initial: "approve",
  },
  acknowledge: {
    heading: "Record your handling",
    lead:
      "Drafting was blocked or produced nothing, so there is no draft to accept. " +
      "Record how this case was handled so there is still an audit trail.",
    submit: "Record handling",
    options: [
      ["acknowledge", "Reviewed and handled", "assessed and managed outside this tool"],
      ["escalate", "Escalated", "referred on for urgent clinical attention"],
    ],
    initial: "acknowledge",
  },
};

const REVIEW_STATUSES = new Set([
  "READY_FOR_CLINICIAN_REVIEW",
  "CITATION_AUDIT_FAILED",
  "SYNTHESIS_EMPTY",
]);

export default function DecisionPanel({ patientId, status, draft, audit, evidenceIds }) {
  const mode = REVIEW_STATUSES.has(status) && draft ? "review" : "acknowledge";
  const m = MODES[mode];
  const [decision, setDecision] = useState(m.initial);
  const [nameErr, setNameErr] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [recorded, setRecorded] = useState(null);
  const nameRef = useRef();
  const notesRef = useRef();

  async function submit(e) {
    e.preventDefault();
    if (busy || recorded) return;
    const clinician = nameRef.current.value.trim();
    if (!clinician) {
      setNameErr(true);
      nameRef.current.focus();
      return;
    }
    setNameErr(false);
    setBusy(true);
    setErr(null);
    try {
      const rec = await postDecision({
        patient_id: patientId,
        clinician,
        decision,
        notes: notesRef.current.value.trim(),
        status,
        draft,
        citation_audit: audit,
        evidence_ids: evidenceIds,
      });
      setRecorded(rec);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (recorded) {
    return (
      <section className="decide decide--done">
        <h3 className="sub-head">Clinician decision</h3>
        <div className="recorded" role="status">
          <b>{LABEL[recorded.decision] || recorded.decision}</b> by {recorded.clinician},{" "}
          {recorded.recorded_at}.
          {recorded.notes ? <> Notes: {recorded.notes}</> : null}
        </div>
        <p className="decide-note">
          This draft is now locked. Re-run the case to review it again.
        </p>
        <div className="decide-actions no-print">
          <button type="button" className="run-btn" onClick={() => window.print()}>
            Save as PDF <span className="arrow">→</span>
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="decide">
      <h3 className="sub-head">{m.heading}</h3>
      <p className="decide-note">{m.lead}</p>

      {mode === "review" && audit?.status === "CITATION_AUDIT_FAILED" && (
        <div className="audit-banner" data-tone={(audit.invalid_evidence_ids || []).length > 0 ? "bad" : "info"}>
          {(audit.invalid_evidence_ids || []).length > 0 ? (
            <>
              One or more citations on this draft don't match a retrieved passage — see the
              flagged evidence above. Recording a decision here does not clear that flag; it's
              captured alongside your decision so the record shows what you decided in spite of it.
            </>
          ) : (
            <>
              A couple of plan items above don't point to a specific passage — worth a quick look
              before you decide. It's captured alongside your decision either way.
            </>
          )}
        </div>
      )}

      <p className="decide-pending-print">Not yet reviewed by a clinician.</p>

      <form onSubmit={submit} noValidate>
        <label className="field">
          <span>Your name *</span>
          <input
            ref={nameRef}
            type="text"
            autoComplete="name"
            aria-invalid={nameErr || undefined}
            onChange={() => nameErr && setNameErr(false)}
          />
          {nameErr && (
            <span className="field__err" role="alert">
              Enter your name before recording.
            </span>
          )}
        </label>

        <fieldset className="decisions">
          <legend>{mode === "acknowledge" ? "How was this handled?" : "Decision"}</legend>
          {m.options.map(([val, strong, rest]) => (
            <label className="dec" key={val}>
              <input
                type="radio"
                name="decision"
                value={val}
                checked={decision === val}
                onChange={() => setDecision(val)}
              />
              <span>
                <b>{strong}</b> — {rest}
              </span>
            </label>
          ))}
        </fieldset>

        <label className="field">
          <span>{mode === "acknowledge" ? "What was done" : "Notes or required changes"}</span>
          <textarea ref={notesRef} rows={3} />
        </label>

        <div className="decide-actions">
          <button type="submit" className="run-btn" disabled={busy}>
            {busy ? "recording…" : m.submit} <span className="arrow">→</span>
          </button>
          <button
            type="button"
            className="run-btn"
            disabled
            title="Record a decision to enable saving as PDF"
          >
            Save as PDF <span className="arrow">→</span>
          </button>
        </div>
        {err && (
          <span className="field__err" role="alert">
            {err}
          </span>
        )}
      </form>
    </section>
  );
}
