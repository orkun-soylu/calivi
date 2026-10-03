// Agent-mode timeline (#91): one view model for a reply's tool steps, whether they come from
// the database (`message.steps`, provider-shaped) or arrive live on the stream. Reloaded and
// live therefore render identically.
//
// An item is either
//   { kind: "text", text }                        — the model's own words between steps
//   { kind: "call", id, name, args, status, output, approval, rule }
// approval: null (none needed) | "approved" | "denied" | "rule" (an "always allow" rule, #113)
// with status "running" | "ok" | "failed" | "denied" | "interrupted".
//
// SECURITY: `output` is what a tool returned and `args` is model-generated. Both are untrusted and
// are only ever rendered as plain text (StepTimeline), never markdown or HTML.

/** Persisted steps → timeline items. Results are matched to their call by `tool_call_id`. */
export function toTimeline(steps) {
  const items = [];
  const byId = new Map();
  for (const s of steps || []) {
    if (s.role === "tool") {
      const item = byId.get(s.tool_call_id);
      if (item) Object.assign(item, finished(s.ok, s.approval, s.content), s.rule ? { rule: s.rule } : {});
      continue;
    }
    if ((s.content || "").trim()) items.push({ kind: "text", text: s.content });
    for (const c of s.tool_calls || []) {
      // No result recorded: the turn was stopped while this call was running or waiting.
      const item = { kind: "call", id: c.id, name: c.name, args: c.arguments || {}, status: "interrupted", output: "", approval: null };
      items.push(item);
      byId.set(c.id, item);
    }
  }
  return items;
}

function finished(ok, approval, output) {
  const status = approval === "denied" ? "denied" : ok ? "ok" : "failed";
  return { status, approval: approval || null, output: output || "" };
}

/** Live stream events → the next items. Pure; the caller moves streamed text in first. */
export function applyPiece(items, piece) {
  const last = items.length - 1;
  const lastCall = () => {
    for (let i = last; i >= 0; i--) if (items[i].kind === "call") return i;
    return -1;
  };
  switch (piece.type) {
    case "tool_call":
      return [...items, { kind: "call", id: null, name: piece.name, args: piece.args || {}, status: "running", output: "", approval: null }];
    case "approval_request": {
      const i = lastCall();
      return i < 0 ? items : replace(items, i, { awaiting: true });
    }
    case "approval_result": {
      const i = lastCall();
      if (i < 0) return items;
      if (piece.rule) return replace(items, i, { awaiting: false, approval: "rule", rule: piece.rule });
      return replace(items, i, { awaiting: false, approval: piece.approved ? "approved" : "denied" });
    }
    case "tool_result": {
      const i = lastCall();
      if (i < 0) return items;
      return replace(items, i, finished(piece.ok, items[i].approval, piece.output));
    }
    default:
      return items;
  }
}

function replace(items, i, patch) {
  const copy = items.slice();
  copy[i] = { ...copy[i], ...patch };
  return copy;
}

/** The one-line summary of a call: the command for a shell, the path for a file tool. */
export function callSummary(name, args) {
  if (typeof args?.command === "string") return args.command;
  if (typeof args?.path === "string") return args.path;
  const json = JSON.stringify(args || {});
  return json === "{}" ? "" : json;
}
