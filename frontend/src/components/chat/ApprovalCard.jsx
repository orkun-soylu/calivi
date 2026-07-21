import { useState } from "react";
import { useT } from "../../i18n.js";

// A state-changing tool is waiting on a decision. The stream is still open behind this card.
//
// SECURITY: `args` is model-generated and therefore untrusted. An injected model will try to
// make a dangerous call look harmless, so this renders raw JSON in a <pre> — never markdown,
// never HTML, and never a summary. Summarising is precisely the vulnerability: the operator
// has to see exactly what will run.
export default function ApprovalCard({ approval, onDecide }) {
  const t = useT();
  const [busy, setBusy] = useState(false);

  async function decide(approved) {
    setBusy(true);
    try {
      await onDecide(approval.id, approved);
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
      <div className="flex gap-2">
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
      </div>
    </div>
  );
}
