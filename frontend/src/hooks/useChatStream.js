import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { applyPiece } from "../lib/timeline.js";

const STEP_EVENTS = new Set(["tool_call", "approval_request", "approval_result", "tool_result"]);

/** All state for one NDJSON stream turn: live text, thinking, tool/search events, cancellation.
 *
 * A reply runs on the server as a background task (#85); this hook only *follows* it. So there
 * are two different ways to leave a stream:
 *   - `stop()` — Stop / Esc: asks the server to cancel the reply. The stream then ends by
 *     itself once the partial reply is saved.
 *   - `detach()` — the user switched chats: stop following. The reply keeps running, and
 *     opening the chat again re-attaches to it.
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
  const [approval, setApproval] = useState(null); // pending tool approval, or null
  // Agent mode (#91): the reply's steps as they happen, in the same shape as a saved reply's.
  const [timeline, setTimeline] = useState([]);
  const agentRef = useRef(false);
  const textRef = useRef(""); // agent mode: text since the last step
  const abortRef = useRef(null);
  const runIdRef = useRef(0); // which run owns the state (see `run`)
  const chatIdRef = useRef(null); // the chat whose reply is being followed

  function stop() {
    // Without a chat id (a fork before its new chat is known) there is nothing to cancel by
    // name; dropping the connection is the best available, and the fork's reply runs on.
    if (chatIdRef.current != null) api.cancelTurn(chatIdRef.current).catch(() => {});
    else abortRef.current?.abort();
  }

  function detach() {
    abortRef.current?.abort();
  }

  /** A fork learns its new chat's id from a response header, mid-stream. */
  function setChatId(id) {
    chatIdRef.current = id;
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
    if (agentRef.current && STEP_EVENTS.has(piece.type)) {
      // A new step closes the text before it: that text becomes its own timeline item, exactly
      // as the backend stores it, and the live bubble starts over.
      const text = piece.type === "tool_call" ? textRef.current : "";
      if (text) {
        textRef.current = "";
        setStreaming("");
      }
      setTimeline((prev) => applyPiece(text.trim() ? [...prev, { kind: "text", text }] : prev, piece));
    }
    if (piece.type === "thinking") setThinking((prev) => prev + piece.text);
    else if (piece.type === "content") {
      textRef.current += piece.text;
      setStreaming((prev) => prev + piece.text);
    }
    else if (piece.type === "search") setSearchInfo(piece);
    // Tool events: the tool the model invoked and its result are shown in the activity line.
    else if (piece.type === "tool_call") setSearchInfo({ status: "tool_running", name: piece.name });
    else if (piece.type === "tool_result")
      setSearchInfo({ status: piece.ok ? "tool_done" : "tool_failed", name: piece.name });
    // A state-changing tool is waiting on a human. The stream stays open while the card is up.
    else if (piece.type === "approval_request")
      setApproval({ id: piece.id, name: piece.name, args: piece.args });
    else if (piece.type === "approval_result") setApproval(null);
    // Keep-alive emitted while waiting for a decision — no bytes would flow otherwise and
    // proxies drop idle connections. Nothing to display.
    else if (piece.type === "ping") return;
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
    setTimeline([]);
    textRef.current = "";
    setStreaming("");
    setThinking("");
    setApproval(null);
    setSearchInfo(null);
  }

  /** `call({ signal, onPiece })` runs the stream; errors, cancellation and cleanup are handled here. */
  async function run(call, { chatId = null, agent = false, beforeClear, afterClear } = {}) {
    // One stream at a time. A new run replaces one still being followed — a re-attach racing
    // another, or React running an effect twice (StrictMode does, on purpose): its connection is
    // dropped, its events are ignored, and its cleanup must not clear the new run's state.
    // Without this a reloaded agent reply rendered its whole timeline twice.
    abortRef.current?.abort();
    const id = ++runIdRef.current;
    const current = () => runIdRef.current === id;
    setSending(true);
    clear();
    agentRef.current = agent;
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    chatIdRef.current = chatId;
    try {
      await call({ signal: ctrl.signal, onPiece: (piece) => current() && onPiece(piece) });
    } catch (e) {
      if (current()) await handleStreamError(e);
    } finally {
      if (current()) {
        abortRef.current = null;
        chatIdRef.current = null;
        if (beforeClear) await beforeClear();
      }
      // Checked again: `beforeClear` awaits a reload, and a new run may have started meanwhile.
      if (current()) {
        setSending(false);
        clear();
        if (afterClear) afterClear();
      }
    }
  }


  /** For showing non-stream errors (e.g. document extraction) in the same bubble. */
  function flashError(text) {
    setStreaming(`⚠️ ${text}`);
    setTimeout(() => setStreaming(""), 2500);
  }

  return {
    streaming, thinking, sending, searchInfo, approval, timeline, run, stop, detach, setChatId, flashError,
    followedChatId: () => chatIdRef.current,
  };
}
