import { useRef, useState } from "react";
import { login } from "../lib/manus.js";

export default function Login({ onSuccess }) {
  const ref = useRef();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function submit(e) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      await login(ref.current.value);
      onSuccess();
    } catch (e) {
      setErr(e.message || "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <span className="mark">PTA</span>
        <p className="login-lead">Admin sign-in — this console handles synthetic PTSD case data.</p>
        <label className="field">
          <span>Password</span>
          <input
            ref={ref}
            type="password"
            autoComplete="current-password"
            autoFocus
            aria-invalid={err ? true : undefined}
          />
        </label>
        {err && (
          <span className="field__err" role="alert">
            {err}
          </span>
        )}
        <button type="submit" className="run-btn" disabled={busy}>
          {busy ? "signing in…" : "sign in"} <span className="arrow">→</span>
        </button>
      </form>
    </div>
  );
}
