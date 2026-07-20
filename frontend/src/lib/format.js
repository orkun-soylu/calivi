// Presentation helpers — pure functions, independent of React (testable).

export function formatTs(ts) {
  if (!ts) return "";
  // The backend returns UTC-naive ISO; if there is no offset, append "Z" and convert to local time.
  const d = new Date(/[Z+]/.test(ts) ? ts : ts + "Z");
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}.${String(d.getFullYear()).slice(-2)} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

// Turns the {type:"search"} event from the backend into user-facing text.
export function searchLabel(t, info) {
  if (!info) return "";
  switch (info.status) {
    case "generating":
      return t("search.generating");
    case "searching":
      return t("search.searching", { query: info.query });
    case "done":
      return t("search.done", { query: info.query, count: info.count });
    case "empty":
      return t("search.empty", { query: info.query });
    case "skip":
      return t("search.skip");
    case "tool_running":
      return t("tools.running", { name: info.name });
    case "tool_done":
      return t("tools.done", { name: info.name });
    case "tool_failed":
      return t("tools.failed", { name: info.name });
    default:
      return "🔍";
  }
}

// Generation speed in the assistant footer. "~" on cloud models, where the measurement
// includes prompt processing and network time.
export function tokensPerSecLabel(m) {
  if (!m.tokens_per_sec) return "";
  return `${m.model_used?.includes(":cloud") ? "~" : ""}${Math.round(m.tokens_per_sec)} t/s`;
}
