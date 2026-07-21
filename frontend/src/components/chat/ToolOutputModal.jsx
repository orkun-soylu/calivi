import { useEffect } from "react";
import { useT } from "../../i18n.js";

// What a tool actually returned, shown verbatim.
//
// SECURITY: this text is external content — a web page, a documentation server's response — and
// is untrusted by definition. It is rendered as PLAIN TEXT in a <pre>, never as markdown and
// never as HTML. That is the whole point of the panel: the operator has to see the material as
// it arrived, not a rendering of it, to check an answer against what was really retrieved.
export default function ToolOutputModal({ tool, onClose }) {
  const t = useT();

  // capture:true + stopPropagation, exactly as the lightbox does: useChatStream also binds
  // Escape on window to cancel the stream, and closing this panel must not throw away an
  // answer that is still generating. Capture runs first regardless of registration order.
  useEffect(() => {
    if (!tool) return;
    function onKey(e) {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      onClose();
    }
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [tool, onClose]);

  if (!tool) return null;
  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-6"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="bg-neutral-900 rounded-2xl ring-1 ring-neutral-700/60 shadow-2xl w-full max-w-3xl max-h-[80vh] flex flex-col"
      >
        <div className="flex items-center gap-3 px-5 py-3 border-b border-neutral-800">
          <span className="text-sm text-neutral-200 truncate">{tool.name}</span>
          <span className="text-xs text-neutral-500 shrink-0">{t("tools.rawOutput")}</span>
          <button onClick={onClose} className="ml-auto text-neutral-500 hover:text-neutral-200">
            ✕
          </button>
        </div>
        <pre className="flex-1 overflow-auto themed-scroll px-5 py-4 text-xs text-neutral-300 whitespace-pre-wrap break-words">
          {tool.detail}
        </pre>
        <p className="px-5 py-2.5 border-t border-neutral-800 text-xs text-neutral-500">
          {t("tools.rawHint")}
        </p>
      </div>
    </div>
  );
}
