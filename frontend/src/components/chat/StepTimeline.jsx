import { useState } from "react";
import Markdown from "../Markdown.jsx";
import ApprovalCard from "./ApprovalCard.jsx";
import { callSummary } from "../../lib/timeline.js";
import { useT } from "../../i18n.js";

const STATUS = {
  running: { icon: "⏳", cls: "text-neutral-400" },
  ok: { icon: "✓", cls: "text-green-400" },
  failed: { icon: "✗", cls: "text-red-400" },
  denied: { icon: "⛔", cls: "text-amber-400" },
  interrupted: { icon: "■", cls: "text-neutral-500" },
};

/** An agent reply's steps (#91): the model's words, and each tool call as a row that expands
 * to its arguments and output. The approval card of a call that is waiting renders in its row.
 *
 * SECURITY: arguments are model-generated and output is whatever the tool returned — both
 * untrusted. They are plain text in <pre>/<code>, never markdown and never HTML. Only the
 * model's own words between steps go through Markdown, as a reply's content always has. */
export default function StepTimeline({ items, approval, onDecide }) {
  if (!items?.length) return null;
  return (
    <div className="mb-2 space-y-1.5">
      {items.map((item, i) =>
        item.kind === "text" ? (
          <Markdown key={i} content={item.text} />
        ) : (
          <CallRow key={i} item={item} approval={item.awaiting ? approval : null} onDecide={onDecide} />
        )
      )}
    </div>
  );
}

function CallRow({ item, approval, onDecide }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const status = STATUS[item.status] || STATUS.running;
  const summary = callSummary(item.name, item.args);
  return (
    <div className="rounded-lg bg-neutral-900/70 ring-1 ring-neutral-700/50 text-xs">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title={t(`timeline.${item.status}`)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left hover:bg-neutral-800/60 rounded-lg"
      >
        <span className={`shrink-0 ${status.cls} ${item.status === "running" ? "animate-pulse" : ""}`}>{status.icon}</span>
        <span className="shrink-0 text-neutral-400">{item.name}</span>
        <code className="min-w-0 flex-1 truncate font-mono text-neutral-200">{summary}</code>
        <span className="shrink-0 text-neutral-500">{open ? "▾" : "▸"}</span>
      </button>
      {item.approval === "rule" && item.rule && (
        <div className="px-2.5 pb-1.5 -mt-0.5 text-neutral-500 truncate">
          {t("rules.approvedBy", { rule: `${t(`rules.kind.${item.rule.kind}`)} ${item.rule.pattern}` })}
        </div>
      )}
      {approval && (
        <div className="px-2.5 pb-2">
          <ApprovalCard approval={approval} onDecide={onDecide} />
        </div>
      )}
      {open && (
        <div className="px-2.5 pb-2.5 space-y-2">
          <pre className="themed-scroll max-h-40 overflow-auto rounded-md bg-neutral-950 p-2 text-neutral-400 whitespace-pre-wrap break-words">
            {JSON.stringify(item.args ?? {}, null, 2)}
          </pre>
          <pre className="themed-scroll max-h-80 overflow-auto rounded-md bg-neutral-950 p-2 text-neutral-300 whitespace-pre-wrap break-words">
            {item.output || t(item.status === "running" ? "timeline.waiting" : "timeline.noOutput")}
          </pre>
        </div>
      )}
    </div>
  );
}
