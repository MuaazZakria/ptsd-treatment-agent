import { motion } from "motion/react";

const CONF = {
  high: { label: "high confidence", cls: "conf-high" },
  moderate: { label: "moderate confidence", cls: "conf-moderate" },
  low: { label: "low confidence", cls: "conf-low" },
};

const AUDIT_COPY = {
  READY_FOR_CLINICIAN_REVIEW: {
    tone: "ok",
    text: "Every recommendation cites a passage that was actually retrieved.",
  },
  SYNTHESIS_EMPTY: {
    tone: "warn",
    text: "Manus did not draft a plan for this profile.",
  },
};

// CITATION_AUDIT_FAILED covers two different situations that don't deserve
// the same tone: a fabricated/unretrieved id is a real integrity problem
// worth flagging plainly; an item that simply didn't cite anything (often a
// general workflow/safety step, not a specific trial finding) is worth a
// second look, not an alarm.
function citationAuditCopy(audit) {
  const hasInvalid = (audit.invalid_evidence_ids || []).length > 0;
  const hasUncited = (audit.options_without_evidence_ids || []).length > 0;
  if (hasInvalid) {
    return {
      tone: "bad",
      text: "One or more citations don't match a retrieved passage — see below.",
    };
  }
  if (hasUncited) {
    return {
      tone: "info",
      text: "A couple of plan items don't point to a specific passage — worth a quick look before you decide.",
    };
  }
  return null;
}

function Chip({ id, invalid, active, onClick }) {
  return (
    <button
      type="button"
      className={`ev-chip${invalid ? " invalid" : ""}${active ? " active" : ""}`}
      onClick={() => onClick(id)}
      title={invalid ? "Not in the retrieved set — the citation check rejected this" : "Show passage"}
    >
      {id}
    </button>
  );
}

export default function Draft({ draft, audit, onCite, selectedEv }) {
  if (!draft) return null;
  const invalidIds = new Set(audit?.invalid_evidence_ids || []);
  const uncited = new Set(audit?.options_without_evidence_ids || []);
  const weakConfidence = new Set(audit?.evidence_quality?.weak_confidence_items || []);
  const a =
    audit &&
    (audit.status === "CITATION_AUDIT_FAILED" ? citationAuditCopy(audit) : AUDIT_COPY[audit.status] || null);
  const plan = draft.recommended_plan || [];

  return (
    <motion.section
      className="draft"
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
    >
      {draft.source === "offline_stub" && (
        <div className="offline-ribbon">
          offline stub — no MANUS_API_KEY. Placeholder plan, not a real synthesis.
        </div>
      )}

      <h3 className="sub-head">Treatment plan — decision support only</h3>
      {draft.assessment && <p className="draft-summary">{draft.assessment}</p>}

      {a && (
        <div className="audit-banner" data-tone={a.tone}>
          {a.text}
          {audit.status === "CITATION_AUDIT_FAILED" && (
            <ul>
              {audit.invalid_evidence_ids.length > 0 && (
                <li>fabricated / unretrieved ids: {audit.invalid_evidence_ids.join(", ")}</li>
              )}
              {audit.options_without_evidence_ids.length > 0 && (
                <li>no specific passage cited: {audit.options_without_evidence_ids.join(", ")}</li>
              )}
            </ul>
          )}
        </div>
      )}

      {audit?.dropped_items?.length > 0 && (
        <div className="audit-banner" data-tone="info">
          {audit.dropped_items.length === 1 ? "One item Manus drafted" : `${audit.dropped_items.length} items Manus drafted`}{" "}
          didn't cite a passage that was actually retrieved, so {audit.dropped_items.length === 1 ? "it was" : "they were"}{" "}
          removed from the plan below rather than shown uncited — kept here for the record, not as a recommendation:
          <ul>
            {audit.dropped_items.map((d) => (
              <li key={d.id}>{d.text}</li>
            ))}
          </ul>
        </div>
      )}

      {plan.length === 0 ? (
        <p className="empty prose">No plan drafted.</p>
      ) : (
        <ol className="options">
          {plan.map((o) => {
            const conf = CONF[o.conf] || CONF.low;
            return (
              <li key={o.id} className={`option-card${uncited.has(o.id) ? " option-uncited" : ""}`}>
                <div className="option-head">
                  {o.cat && <span className="option-cat">{o.cat}</span>}
                  <span className={`conf-badge ${conf.cls}`}>{conf.label}</span>
                </div>
                <p className="option-text">{o.text}</p>
                {o.rationale && <p className="option-why">{o.rationale}</p>}
                {weakConfidence.has(o.id) && (
                  <p className="option-caution-flag">
                    Deterministic check: the cited evidence for this item looks mechanistic or
                    animal-model, not direct clinical treatment evidence — the confidence above
                    may be overstated relative to what's actually cited.
                  </p>
                )}
                {o.cautions?.length > 0 && (
                  <ul className="option-cautions">
                    {o.cautions.map((c, k) => (
                      <li key={k}>{c}</li>
                    ))}
                  </ul>
                )}
                <div className="option-ev">
                  <span className="option-ev-label">evidence</span>
                  {o.ev.length === 0 ? (
                    <span className="ev-chip invalid">no citation</span>
                  ) : (
                    o.ev.map((id) => (
                      <Chip
                        key={id}
                        id={id}
                        invalid={invalidIds.has(id)}
                        active={selectedEv === id}
                        onClick={onCite}
                      />
                    ))
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {draft.monitoring?.length > 0 && (
        <div className="draft-missing">
          <span className="draft-missing-label">monitoring</span>
          <ul>
            {draft.monitoring.map((m, k) => (
              <li key={k}>{m}</li>
            ))}
          </ul>
        </div>
      )}

      {draft.reassessment_triggers?.length > 0 && (
        <div className="draft-missing">
          <span className="draft-missing-label">reassess if</span>
          <ul>
            {draft.reassessment_triggers.map((t, k) => (
              <li key={k}>{t}</li>
            ))}
          </ul>
        </div>
      )}

      {draft.missing?.length > 0 && (
        <div className="draft-missing">
          <span className="draft-missing-label">before you decide</span>
          <ul>
            {draft.missing.map((m, k) => (
              <li key={k}>{m}</li>
            ))}
          </ul>
        </div>
      )}
    </motion.section>
  );
}
