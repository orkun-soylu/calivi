import { useState } from "react";
import { useT } from "../../i18n.js";

export function CopyButton({ text }) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* no clipboard access — fail silently */
    }
  }
  return (
    <button onClick={copy} title={t("chat.copyAnswer")} className="opacity-70 hover:opacity-100 shrink-0">
      {copied ? (
        <span className="text-green-400">✓</span>
      ) : (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
      )}
    </button>
  );
}

export function DeleteButton({ onDelete }) {
  const t = useT();
  return (
    <button
      onClick={onDelete}
      title={t("chat.deleteMessage")}
      className="opacity-70 hover:opacity-100 hover:text-red-400 shrink-0"
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="18" y1="6" x2="6" y2="18" />
        <line x1="6" y1="6" x2="18" y2="18" />
      </svg>
    </button>
  );
}

export function EditButton({ onEdit }) {
  const t = useT();
  return (
    <button onClick={onEdit} title={t("chat.editMessage")} className="opacity-70 hover:opacity-100 shrink-0">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 20h9" />
        <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
      </svg>
    </button>
  );
}

// Document attachment chip (📎 file name). If onRemove is given it can be removed with ×.
// onAccent: when the chip sits on a colored (accent) message bubble. The neutral palette
// inverts to near-white in the light theme, which left white bubble text on a near-white chip
// (unreadable). On an accent bubble use a translucent-white chip that stays legible in both themes.
export function AttachmentChip({ name, onRemove, onAccent = false, onInspect }) {
  const t = useT();
  const tone = onAccent ? "bg-white/20 text-white" : "bg-neutral-800";
  // A chip that carries what a tool returned becomes a button: the point is being able to check
  // the answer against the material it claims to come from.
  const inspectable = typeof onInspect === "function";
  return (
    <span
      onClick={inspectable ? onInspect : undefined}
      title={inspectable ? t("tools.inspect") : undefined}
      className={`inline-flex items-center gap-1.5 rounded-lg ${tone} px-2 py-1 text-xs max-w-[220px] ${
        inspectable ? "cursor-pointer hover:ring-1 hover:ring-white/30" : ""
      }`}
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
        <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
      </svg>
      <span className="truncate">{name}</span>
      {onRemove && (
        <button onClick={onRemove} title={t("common.remove")} className="opacity-70 hover:opacity-100 hover:text-red-400 shrink-0">
          ✕
        </button>
      )}
    </span>
  );
}
