import { useState } from "react";
import { api } from "../api.js";
import { useT } from "../i18n.js";

// Sign-in / sign-up screen. App shows this when there is no session.
// With registrationEnabled=false only sign-in is available (the signup tab is hidden).
export default function AuthView({ registrationEnabled, onAuthed }) {
  const t = useT();
  const [mode, setMode] = useState("signin"); // "signin" | "signup"
  const [identifier, setIdentifier] = useState("");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const isSignup = mode === "signup" && registrationEnabled;

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const user = isSignup
        ? await api.register({ email, username, password })
        : await api.login({ identifier, password });
      onAuthed(user);
    } catch (err) {
      // A request() error has the form "STATUS body"; peel off the body.
      const msg = String(err.message || "");
      const detail = msg.replace(/^\d+\s*/, "");
      let text = detail;
      try {
        text = JSON.parse(detail).detail || detail;
      } catch {
        /* düz metin */
      }
      setError(text || t("auth.genericError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center justify-center h-screen w-full bg-neutral-950">
      <form
        onSubmit={submit}
        className="w-80 bg-neutral-900 rounded-2xl shadow-2xl ring-1 ring-neutral-700/60 p-6 flex flex-col gap-3"
      >
        <div className="text-center mb-1">
          <div className="text-2xl text-neutral-100">Calivi</div>
          <div className="text-xs text-neutral-500 mt-1">{t("auth.tagline")}</div>
        </div>

        {registrationEnabled && (
          <div className="flex gap-1 bg-neutral-800/60 rounded-lg p-1 text-sm">
            <button
              type="button"
              onClick={() => { setMode("signin"); setError(""); }}
              className={`flex-1 py-1.5 rounded-md ${mode === "signin" ? "bg-neutral-700 text-neutral-100" : "text-neutral-400"}`}
            >
              {t("auth.signin")}
            </button>
            <button
              type="button"
              onClick={() => { setMode("signup"); setError(""); }}
              className={`flex-1 py-1.5 rounded-md ${mode === "signup" ? "bg-neutral-700 text-neutral-100" : "text-neutral-400"}`}
            >
              {t("auth.signup")}
            </button>
          </div>
        )}

        {isSignup ? (
          <>
            <input
              type="email" value={email} onChange={(e) => setEmail(e.target.value)}
              placeholder={t("auth.email")} autoComplete="email"
              className="bg-neutral-800 rounded-lg px-3 py-2 text-sm"
            />
            <input
              value={username} onChange={(e) => setUsername(e.target.value)}
              placeholder={t("auth.username")} autoComplete="username"
              className="bg-neutral-800 rounded-lg px-3 py-2 text-sm"
            />
          </>
        ) : (
          <input
            value={identifier} onChange={(e) => setIdentifier(e.target.value)}
            placeholder={t("auth.identifier")} autoComplete="username"
            className="bg-neutral-800 rounded-lg px-3 py-2 text-sm"
          />
        )}

        <input
          type="password" value={password} onChange={(e) => setPassword(e.target.value)}
          placeholder={t("auth.password")} autoComplete={isSignup ? "new-password" : "current-password"}
          className="bg-neutral-800 rounded-lg px-3 py-2 text-sm"
        />

        {error && <div className="text-xs text-red-500 dark:text-red-400">{error}</div>}

        <button
          type="submit" disabled={busy}
          className="mt-1 px-3 py-2 rounded-lg bg-accent hover:bg-accent-hover disabled:opacity-50 text-sm"
        >
          {isSignup ? t("auth.signupBtn") : t("auth.signinBtn")}
        </button>

        {!registrationEnabled && (
          <div className="text-center text-xs text-neutral-600">{t("auth.registrationClosed")}</div>
        )}
      </form>
    </div>
  );
}
