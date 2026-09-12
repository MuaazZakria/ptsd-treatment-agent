import { motion } from "motion/react";

export default function EvidencePassages({ evidence = [], selected, onSelect }) {
  if (!evidence.length) return null;
  return (
    <section className="passages">
      <h3 className="sub-head">Retrieved Evidence · {evidence.length}</h3>
      <p className="passages-note">
        The only evidence Manus was given. Every citation below must resolve to one of these.
      </p>
      {evidence.map((e, i) => (
        <motion.article
          key={e.evidence_id}
          id={`ev-${e.evidence_id}`}
          className={`passage${selected === e.evidence_id ? " highlight" : ""}`}
          onClick={() => onSelect(selected === e.evidence_id ? null : e.evidence_id)}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: Math.min(i, 6) * 0.04, duration: 0.35 }}
        >
          <div className="passage-meta">
            <span className="passage-id">{e.evidence_id}</span>
            <span className="passage-bm25">bm25 {e.raw_bm25}</span>
          </div>
          <div className="passage-title">{e.title}</div>
          <div className="passage-src">
            {e.file} · p.{e.page}
          </div>
        </motion.article>
      ))}
    </section>
  );
}
