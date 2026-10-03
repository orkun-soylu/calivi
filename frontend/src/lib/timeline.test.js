import { describe, expect, test } from "vitest";
import { applyPiece, callSummary, toTimeline } from "./timeline.js";

const call = (id, command) => ({ id, name: "bash", arguments: { command } });

describe("toTimeline — persisted steps", () => {
  test("text, calls and results in order; results matched by id", () => {
    const items = toTimeline([
      { role: "assistant", content: "Checking.", tool_calls: [call("a", "ls"), call("b", "df -h")] },
      { role: "tool", tool_call_id: "b", content: "disk", ok: true, approval: null },
      { role: "tool", tool_call_id: "a", content: "files", ok: true, approval: null },
    ]);
    expect(items.map((i) => i.kind)).toEqual(["text", "call", "call"]);
    expect(items[1]).toMatchObject({ name: "bash", status: "ok", output: "files" });
    expect(items[2]).toMatchObject({ status: "ok", output: "disk" });
  });

  test("denied, failed, and a call with no result (the turn was stopped)", () => {
    const items = toTimeline([
      { role: "assistant", content: "", tool_calls: [call("a", "rm x"), call("b", "false"), call("c", "sleep 99")] },
      { role: "tool", tool_call_id: "a", content: "not approved", ok: false, approval: "denied" },
      { role: "tool", tool_call_id: "b", content: "exit 1", ok: false, approval: null },
    ]);
    expect(items.map((i) => i.status)).toEqual(["denied", "failed", "interrupted"]);
  });
});

describe("applyPiece — live events", () => {
  test("a call runs, waits for approval, and finishes with its output", () => {
    let items = applyPiece([], { type: "tool_call", name: "bash", args: { command: "rm x" } });
    expect(items[0].status).toBe("running");
    items = applyPiece(items, { type: "approval_request", id: "p1", name: "bash", args: {} });
    expect(items[0].awaiting).toBe(true);
    items = applyPiece(items, { type: "approval_result", name: "bash", approved: false });
    items = applyPiece(items, { type: "tool_result", name: "bash", ok: false, output: "not approved" });
    expect(items[0]).toMatchObject({ awaiting: false, status: "denied", output: "not approved" });
  });

  test("the same shape as the persisted form", () => {
    let live = [{ kind: "text", text: "Checking." }];
    live = applyPiece(live, { type: "tool_call", name: "bash", args: { command: "ls" } });
    live = applyPiece(live, { type: "tool_result", name: "bash", ok: true, output: "files" });
    const saved = toTimeline([
      { role: "assistant", content: "Checking.", tool_calls: [call("x", "ls")] },
      { role: "tool", tool_call_id: "x", content: "files", ok: true, approval: null },
    ]);
    const strip = (items) => items.map(({ id, awaiting, ...rest }) => rest);
    expect(strip(live)).toEqual(strip(saved));
  });
});

test("callSummary: the command, the path, or the arguments", () => {
  expect(callSummary("bash", { command: "uptime" })).toBe("uptime");
  expect(callSummary("read_file", { path: "/etc/hosts" })).toBe("/etc/hosts");
  expect(callSummary("mcp__x__y", { q: 1 })).toBe('{"q":1}');
  expect(callSummary("t", {})).toBe("");
});

describe("always-allow rules (#113)", () => {
  const rule = { id: 3, tool: "bash", kind: "exact", pattern: "sudo systemctl restart ollama" };

  test("a rule's yes is marked as the rule's, live and reloaded", () => {
    let items = applyPiece([], { type: "tool_call", name: "bash", args: { command: rule.pattern } });
    items = applyPiece(items, { type: "approval_result", name: "bash", approved: true, rule });
    items = applyPiece(items, { type: "tool_result", name: "bash", ok: true, output: "exit code: 0" });
    expect(items[0]).toMatchObject({ status: "ok", approval: "rule", rule });

    const saved = toTimeline([
      { role: "assistant", content: "", tool_calls: [{ id: "c1", name: "bash", arguments: { command: rule.pattern } }] },
      { role: "tool", tool_call_id: "c1", name: "bash", content: "exit code: 0", ok: true, approval: "rule", rule },
    ]);
    expect(saved[0]).toMatchObject({ status: "ok", approval: "rule", rule });
  });
});
