import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { CHAT_TYPES, payloadOf, tsMs } from "../lib/manus.js";

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return <time className="clock">{now.toLocaleTimeString([], { hour12: false })}</time>;
}

const stamp = (e) => {
  const ms = tsMs(e);
  return (ms ? new Date(ms) : new Date()).toLocaleTimeString([], { hour12: false });
};

const isNoise = (e) =>
  e.type === "tool_used" && payloadOf(e).message?.action === "suggestion";

function nodeClass(e) {
  const p = payloadOf(e);
  if (e.type === "tool_used")
    return p.status === "success" ? "node-teal" : p.status === "error" ? "node-rust" : "node-ember";
  if (e.type === "status_update") return "node-brass";
  return "node-hollow";
}

function TelemetryRow({ e, i }) {
  const p = payloadOf(e);
  const kind = e.type === "tool_used" ? p.tool || "tool" : e.type.replace(/_/g, " ");
  const brief =
    p.brief || p.content || p.text || (p.message && p.message.action) || p.agent_status || "";
  const desc = p.description && p.description !== brief ? p.description : null;

  return (
    <motion.li
      className="trow"
      initial={{ opacity: 0, x: 14 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.4, delay: Math.min(i, 6) * 0.03, ease: [0.2, 0.7, 0.2, 1] }}
    >
      <span className={`tnode ${nodeClass(e)}`} />
      <div className="tbody">
        <div className="tmeta">
          <span className="tkind">{kind}</span>
          <span className="tstamp">{stamp(e)}</span>
        </div>
        {brief && <p className="tbrief">{brief}</p>}
        {desc && <p className="tdesc">{desc}</p>}
      </div>
    </motion.li>
  );
}

export default function Telemetry({ events, notes = [], status, offline }) {
  const rows = events.filter((e) => !CHAT_TYPES.has(e.type) && !isNoise(e));
  const scroller = useRef(null);
  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [rows.length, notes.length, status]);

  const live = status === "running" || status === "waiting";

  return (
    <motion.section
      className="panel telemetry"
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, delay: 0.18, ease: [0.2, 0.7, 0.2, 1] }}
    >
      <header className="panel-head">
        <h2>Manus Telemetry</h2>
        <Clock />
      </header>
      <div className="panel-scroll" ref={scroller}>
        {notes.map((n, i) => (
          <p key={i} className={`tnote ${n.kind === "warn" ? "tnote--warn" : ""}`}>
            {n.note}
          </p>
        ))}
        {rows.length === 0 ? (
          <p className="empty mono">
            {offline ? "// offline — Manus not called" : "// no telemetry yet"}
          </p>
        ) : (
          <ol className="trail">
            <AnimatePresence initial={false}>
              {rows.map((e, i) => (
                <TelemetryRow key={e._id} e={e} i={i} />
              ))}
            </AnimatePresence>
          </ol>
        )}
        {live && (
          <div className="receiving">
            <span />
            <span />
            <span />
            {status === "waiting" ? "holding for input" : "receiving"}
          </div>
        )}
      </div>
    </motion.section>
  );
}
