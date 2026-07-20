import { useEffect, useRef, useState } from "react";

/** All state for one NDJSON stream turn: live text, thinking, tool/search events, cancellation.
 *
 * send / edit / fork all share the same skeleton (reset state → AbortController →
 * stream → clear). The ONLY difference between them is the `finally` ordering, and that
 * ordering is visually significant, so it is left to the caller via `beforeClear` / `afterClear`:
 *   - send:        `onMessageSent()` is AWAITED first, then the streaming bubble is cleared
 *                  (clearing the bubble before the new message lands shows an empty gap).
 *   - edit / fork: cleared first, `onMessageSent()` is called afterwards and NOT awaited.
 */
export function useChatStream() {
  const [streaming, setStreaming] = useState("");
  const [thinking, setThinking] = useState("");
  const [sending, setSending] = useState(false);
  const [searchInfo, setSearchInfo] = useState(null); // last search/tool event of the active stream
  const abortRef = useRef(null);

  function stop() {
    abortRef.current?.abort();
  }

  // Esc → stop the active stream.
  useEffect(() => {
    if (!sending) return;
    function onKey(e) {
      if (e.key === "Escape") stop();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sending]);

  function onPiece(piece) {
    if (piece.type === "thinking") setThinking((prev) => prev + piece.text);
    else if (piece.type === "content") setStreaming((prev) => prev + piece.text);
    else if (piece.type === "search") setSearchInfo(piece);
    // Tool events: the tool the model invoked and its result are shown in the activity line.
    else if (piece.type === "tool_call") setSearchInfo({ status: "tool_running", name: piece.name });
    else if (piece.type === "tool_result")
      setSearchInfo({ status: piece.ok ? "tool_done" : "tool_failed", name: piece.name });
    // Upstream model error (e.g. HTTP 400): appended to the bubble as a visible marker.
    // The backend persists the same marker into the message content → stays consistent on reload.
    else if (piece.type === "error")
      setStreaming((prev) => (prev ? prev + "\n\n" : "") + "⚠️ " + piece.message);
  }

  // Stream error: on cancellation (AbortError) show no ⚠️, wait for the backend to persist the partial.
  async function handleStreamError(e) {
    if (e.name === "AbortError") {
      await new Promise((r) => setTimeout(r, 500));
    } else {
      setStreaming(`⚠️ ${e.message}`);
      await new Promise((r) => setTimeout(r, 2500));
    }
  }

  function clear() {
    setStreaming("");
    setThinking("");
    setSearchInfo(null);
  }

  /** `call({ signal, onPiece })` runs the stream; errors, cancellation and cleanup are handled here. */
  async function run(call, { beforeClear, afterClear } = {}) {
    setSending(true);
    clear();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      await call({ signal: ctrl.signal, onPiece });
    } catch (e) {
      await handleStreamError(e);
    } finally {
      abortRef.current = null;
      if (beforeClear) await beforeClear();
      setSending(false);
      clear();
      if (afterClear) afterClear();
    }
  }

  /** For showing non-stream errors (e.g. document extraction) in the same bubble. */
  function flashError(text) {
    setStreaming(`⚠️ ${text}`);
    setTimeout(() => setStreaming(""), 2500);
  }

  return { streaming, thinking, sending, searchInfo, run, stop, flashError };
}
