import { useState } from "react";
import { useT } from "../../i18n.js";

// Extracts the backend's reason from a request() error ("STATUS {detail}").
function errText(err) {
  const detail = String(err.message || "").replace(/^\d+\s*/, "");
  try {
    return JSON.parse(detail).detail || detail;
  } catch {
    return detail;
  }
}

// A state-changing tool is waiting on a decision. The stream is still open behind this card.
//
// SECURITY: `args` is model-generated and therefore untrusted. An injected model will try to
// make a dangerous call look harmless, so this renders raw JSON in a <pre> — never markdown,
// never HTML, and never a summary. Summarising is precisely the vulnerability: the operator
// has to see exactly what will run.
//
// "Always allow…" (#113, calivi-vm) appears only when the backend offers a rule for this call:
// the narrowest one, which the owner can edit before saving. The backend refuses a rule that is
// too broad or does not cover this very call, and the card shows why.
export default function ApprovalCard({ approval, onDecide }) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const suggestion = approval.rule_suggestion;
  const [rule, setRule] = useState(null); // the rule being edited, or null
  const [ruleError, setRuleError] = useState("");

  async function decide(approved) {
    setBusy(true);
    try {
      await onDecide(approval.id, approved);
    } finally {
      setBusy(false);
    }
  }

  async function allowAlways() {
    setBusy(true);
    setRuleError("");
    try {
      await onDecide(approval.id, true, { kind: rule.kind, pattern: rule.pattern });
    } catch (e) {
      setRuleError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl border border-amber-500/40 bg-amber-500/5 px-4 py-3 my-2 space-y-2">
      <div className="text-sm text-amber-200">
        {t("approval.title", { name: approval.name })}
      </div>
      <p className="text-xs text-neutral-400">{t("approval.warning")}</p>
      <pre className="text-xs bg-neutral-900 rounded-lg p-2 overflow-x-auto whitespace-pre text-neutral-300">
        {JSON.stringify(approval.args ?? {}, null, 2)}
      </pre>
      {rule && (
        <div className="space-y-1.5 rounded-lg bg-neutral-900/70 p-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {suggestion.kind === "dir" ? (
              <span className="text-neutral-400">{t("rules.kind.dir")}</span>
            ) : (
              <select
                value={rule.kind}
                onChange={(e) => setRule({ ...rule, kind: e.target.value })}
                aria-label={t("rules.kindLabel")}
                className="bg-neutral-800 rounded-md px-1.5 py-1"
              >
                <option value="exact">{t("rules.kind.exact")}</option>
                <option value="prefix">{t("rules.kind.prefix")}</option>
              </select>
            )}
            <input
              value={rule.pattern}
              onChange={(e) => setRule({ ...rule, pattern: e.target.value })}
              aria-label={t("rules.patternLabel")}
              className="flex-1 min-w-0 bg-neutral-800 rounded-md px-2 py-1 font-mono"
            />
          </div>
          <p className="text-xs text-neutral-500">{t(`rules.hint.${rule.kind}`)}</p>
          {ruleError && <p className="text-xs text-red-400">{ruleError}</p>}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {rule ? (
          <>
            <button
              onClick={allowAlways}
              disabled={busy || !rule.pattern.trim()}
              className="px-3 py-1.5 rounded-lg bg-accent hover:bg-accent-hover text-sm disabled:opacity-50"
            >
              {t("rules.saveAndApprove")}
            </button>
            <button
              onClick={() => {
                setRule(null);
                setRuleError("");
              }}
              disabled={busy}
              className="px-3 py-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-sm disabled:opacity-50"
            >
              {t("rules.back")}
            </button>
          </>
        ) : (
          <>
            <button
              onClick={() => decide(true)}
              disabled={busy}
              className="px-3 py-1.5 rounded-lg bg-accent hover:bg-accent-hover text-sm disabled:opacity-50"
            >
              {t("approval.approve")}
            </button>
            <button
              onClick={() => decide(false)}
              disabled={busy}
              className="px-3 py-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-sm disabled:opacity-50"
            >
              {t("approval.deny")}
            </button>
            {suggestion && (
              <button
                onClick={() => setRule({ ...suggestion })}
                disabled={busy}
                className="px-3 py-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-sm disabled:opacity-50"
              >
                {t("rules.alwaysAllow")}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
