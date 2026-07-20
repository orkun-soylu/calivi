import { useEffect, useRef } from "react";
import { AttachmentChip } from "./MessageActions.jsx";
import { useT } from "../../i18n.js";

/** Bottom bar: attach/search buttons, auto-grow textarea, send/stop + attachment previews. */
export default function Composer({
  input,
  onInputChange,
  onSend,
  onStop,
  sending,
  canSend,
  images,
  onRemoveImage,
  attachments,
  onRemoveAttachment,
  onFiles,
  onPaste,
  webSearch,
  onToggleWebSearch,
}) {
  const t = useT();
  const fileInputRef = useRef(null);
  const inputRef = useRef(null);

  // Auto-grow: grow the height as the content grows (max-height lives in CSS → scrollbar beyond it).
  // When the input empties (after sending) it collapses back to a single line.
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [input]);

  function handleFileSelect(e) {
    const files = Array.from(e.target.files || []);
    e.target.value = ""; // so the same file can be picked again
    onFiles(files);
  }

  // Dialog starting folder: a plain <input type="file"> cannot set this (the browser remembers
  // the last used folder). On Chromium the File System Access API pins it to Documents.
  // `id` is DELIBERATELY not passed: per spec (WICG 3.2.2) a registered id mapping overrides
  // startIn, so passing an id would reopen the last folder after the first pick anyway.
  // Firefox/Safari lack the API → <input> fallback.
  // `types` is DELIBERATELY omitted too: the picker always pre-selects types[0] and does not
  // remember the user switching to "All files" → it would snap back to that filter every time.
  // It opens unfiltered; if an unsupported file is picked, addFiles/extract surfaces a readable error.
  async function openPicker() {
    if (window.showOpenFilePicker) {
      try {
        const handles = await window.showOpenFilePicker({
          multiple: true,
          startIn: "documents",
        });
        onFiles(await Promise.all(handles.map((h) => h.getFile())));
        return;
      } catch (err) {
        if (err?.name === "AbortError") return; // the user cancelled
        // Insecure context / restricted directory etc. → silently fall back to <input>
      }
    }
    fileInputRef.current?.click();
  }

  return (
    <div className="px-5 py-5">
      {images.length > 0 && (
        <div className="flex gap-2 flex-wrap mb-2">
          {images.map((src, i) => (
            <div key={i} className="relative">
              <img src={src} alt="" className="h-16 w-16 object-cover rounded-lg" />
              <button
                onClick={() => onRemoveImage(i)}
                title={t("common.remove")}
                className="absolute -top-1.5 -right-1.5 w-5 h-5 flex items-center justify-center rounded-full bg-neutral-900 text-neutral-300 hover:text-red-400 text-xs"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}
      {attachments.length > 0 && (
        <div className="flex gap-2 flex-wrap mb-2">
          {attachments.map((a, i) => (
            <AttachmentChip key={i} name={a.name} onRemove={() => onRemoveAttachment(i)} />
          ))}
        </div>
      )}
      <div className="flex gap-2 items-end">
        <button
          onClick={openPicker}
          title={t("chat.attachDoc")}
          className="h-10 px-4 rounded-xl bg-neutral-800 hover:bg-neutral-700 text-neutral-300 shrink-0 flex items-center justify-center"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
          </svg>
        </button>
        <button
          onClick={onToggleWebSearch}
          title={webSearch ? t("chat.webSearchOn") : t("chat.webSearchOff")}
          className={`h-10 px-4 rounded-xl shrink-0 flex items-center justify-center ${
            webSearch ? "bg-accent text-white hover:bg-accent-hover" : "bg-neutral-800 text-neutral-300 hover:bg-neutral-700"
          }`}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
        </button>
        <textarea
          ref={inputRef}
          value={input}
          rows={1}
          onChange={(e) => onInputChange(e.target.value)}
          onPaste={onPaste}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), onSend())}
          placeholder={t("chat.placeholder")}
          className="themed-scroll flex-1 resize-none max-h-60 bg-neutral-800 rounded-xl px-4 py-2 outline-none border border-neutral-700 focus:border-neutral-500"
        />
        {sending ? (
          <button
            onClick={onStop}
            title={t("chat.stop")}
            className="h-10 px-4 rounded-xl bg-red-600 hover:bg-red-500 flex items-center justify-center"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <rect x="6" y="6" width="12" height="12" rx="1.5" />
            </svg>
          </button>
        ) : (
          <button
            onClick={onSend}
            disabled={!canSend}
            className="h-10 px-4 rounded-xl bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center"
          >
            →
          </button>
        )}
      </div>
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*,.pdf,.docx,.txt,.md,.csv,.json,.yml,.yaml,.log,.py,.js,.jsx,.ts,.tsx,.sh,.html,.css,.xml,.sql,.toml,.ini"
        multiple
        hidden
        onChange={handleFileSelect}
      />
    </div>
  );
}
