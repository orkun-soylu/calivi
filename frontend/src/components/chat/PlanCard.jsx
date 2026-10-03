import { useState } from "react";
import { useT } from "../../i18n.js";

// Plan mode (#114): the plan a reply proposed. Run it / Cancel while it is the chat's last word;
// a reply in the composer is "change it". Afterwards the card shows what was decided.
//
// SECURITY: every field was written by the model, and the commands are what will run on
// approval. Plain text only — commands verbatim in <pre>, never markdown, never a summary — for
// the same reason as the approval card: the owner has to see exactly what they say yes to.
export default function PlanCard({ plan, actions }) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const status = plan.status || "proposed";

  async function act(fn) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl border border-sky-500/40 bg-sky-500/5 px-4 py-3 my-2 space-y-2 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sky-200">{t("plan.title")}</span>
        <span className="text-xs text-neutral-400">{t(`plan.status.${status}`)}</span>
      </div>
      <p className="whitespace-pre-wrap text-neutral-200">{plan.summary}</p>
      <ol className="space-y-2 list-decimal pl-5">
        {(plan.steps || []).map((s, i) => (
          <li key={i} className="space-y-1">
            <span className="whitespace-pre-wrap text-neutral-200">{s.title}</span>
            {(s.commands?.length > 0 || s.files?.length > 0) && (
              <pre className="text-xs bg-neutral-900 rounded-lg p-2 overflow-x-auto whitespace-pre text-neutral-300">
                {[...(s.commands || []).map((c) => `$ ${c}`), ...(s.files || []).map((f) => `${t("plan.file")}: ${f}`)].join("\n")}
              </pre>
            )}
          </li>
        ))}
      </ol>
      {plan.risks && (
        <p className="text-xs whitespace-pre-wrap">
          <span className="text-amber-300">{t("plan.risks")}: </span>
          <span className="text-neutral-300">{plan.risks}</span>
        </p>
      )}
      {plan.rollback && (
        <p className="text-xs whitespace-pre-wrap">
          <span className="text-neutral-400">{t("plan.rollback")}: </span>
          <span className="text-neutral-300">{plan.rollback}</span>
        </p>
      )}
      {status === "proposed" && actions && (
        <div className="space-y-1.5 pt-1">
          <p className="text-xs text-neutral-400">{t("plan.runHint")}</p>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => act(actions.onRun)}
              disabled={busy}
              className="px-3 py-1.5 rounded-lg bg-accent hover:bg-accent-hover text-sm disabled:opacity-50"
            >
              {t("plan.run")}
            </button>
            <button
              onClick={() => act(actions.onCancel)}
              disabled={busy}
              className="px-3 py-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-sm disabled:opacity-50"
            >
              {t("plan.cancel")}
            </button>
            <span className="text-xs text-neutral-500">{t("plan.changeHint")}</span>
          </div>
          {error && <p className="text-xs text-red-400">{error}</p>}
        </div>
      )}
    </div>
  );
}
