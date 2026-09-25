import { useT } from "../../i18n.js";

/** "31k" / "850" — the backend's figure is a chars/4 estimate, so more precision would lie. */
export function formatTokens(n) {
  return n >= 1000 ? `${Math.round(n / 1000)}k` : String(n);
}

/** What the model is being sent for this chat, and the controls for compacting it (#62).
 *
 * Renders nothing for a chat with no summary that has not reached the suggestion threshold —
 * compaction is still reachable from the header button then, without a bar in the way.
 * Compaction is only ever started by the user; the bar suggests, it never acts on its own. */
export default function ContextBar({ chat, compacting, onCompact, onStopCompact, onSetMode, onViewSummary }) {
  const t = useT();
  const hasSummary = !!chat.summary;

  if (compacting) {
    return (
      <Bar>
        <span className="animate-pulse">{t("compact.running", { chars: compacting.chars })}</span>
        <button onClick={onStopCompact} className="ml-auto underline hover:text-neutral-200">
          {t("compact.stop")}
        </button>
      </Bar>
    );
  }

  if (hasSummary) {
    const full = chat.context_mode === "full";
    return (
      <Bar>
        <span>{t("compact.modeLabel")}</span>
        <div className="inline-flex rounded-lg bg-neutral-800 p-0.5" role="group">
          <ModeButton active={!full} onClick={() => onSetMode("compact")}>
            {t("compact.modeCompact")}
          </ModeButton>
          <ModeButton active={full} onClick={() => onSetMode("full")}>
            {t("compact.modeFull")}
          </ModeButton>
        </div>
        <span className="text-neutral-500">~{formatTokens(chat.context_tokens_estimate)}</span>
        <button onClick={onViewSummary} className="underline hover:text-neutral-200">
          {t("compact.viewSummary")}
        </button>
        {chat.compactable && (
          <button onClick={onCompact} className="underline hover:text-neutral-200">
            {t("compact.again")}
          </button>
        )}
      </Bar>
    );
  }

  if (chat.compact_suggested) {
    return (
      <Bar>
        <span>{t("compact.suggest", { tokens: formatTokens(chat.context_tokens_estimate) })}</span>
        <button
          onClick={onCompact}
          className="ml-auto shrink-0 rounded-lg bg-accent px-2.5 py-1 text-white hover:opacity-90"
        >
          {t("compact.button")}
        </button>
      </Bar>
    );
  }

  return null;
}

function Bar({ children }) {
  return (
    <div className="mx-3 md:mx-5 mb-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-xl bg-neutral-900 px-3 py-2 text-xs text-neutral-400">
      {children}
    </div>
  );
}

function ModeButton({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-md px-2 py-0.5 ${active ? "bg-neutral-700 text-neutral-100" : "hover:text-neutral-200"}`}
    >
      {children}
    </button>
  );
}
