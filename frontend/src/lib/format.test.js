import { describe, expect, test } from "vitest";
import { formatTs, searchLabel, tokensPerSecLabel } from "./format.js";

describe("formatTs", () => {
  test("empty value gives an empty string", () => {
    expect(formatTs(null)).toBe("");
    expect(formatTs("")).toBe("");
  });

  test("a backend stamp without an offset is treated as UTC", () => {
    // The backend returns UTC-naive ISO; without the added "Z" the browser reads it as local time and shifts it.
    const implicit = formatTs("2026-07-19T12:00:00");
    const explicitUtc = formatTs("2026-07-19T12:00:00Z");
    expect(implicit).toBe(explicitUtc);
  });

  test("day/month/time are zero-padded to two digits", () => {
    expect(formatTs("2026-01-05T03:04:05Z")).toMatch(/^05\.01\.26 \d{2}:\d{2}:\d{2}$/);
  });
});

describe("searchLabel", () => {
  const t = (key, params) => (params ? `${key}:${JSON.stringify(params)}` : key);

  test("empty when there is no info", () => {
    expect(searchLabel(t, null)).toBe("");
  });

  test("tool events map to tools.* keys", () => {
    expect(searchLabel(t, { status: "tool_running", name: "web_search" })).toBe(
      'tools.running:{"name":"web_search"}'
    );
    expect(searchLabel(t, { status: "tool_done", name: "web_search" })).toContain("tools.done");
    expect(searchLabel(t, { status: "tool_failed", name: "web_search" })).toContain("tools.failed");
  });

  test("search events map to search.* keys", () => {
    expect(searchLabel(t, { status: "searching", query: "x" })).toContain("search.searching");
    expect(searchLabel(t, { status: "done", query: "x", count: 3 })).toContain("search.done");
  });

  test("an unknown status does not crash, it falls back to the icon", () => {
    expect(searchLabel(t, { status: "something-new" })).toBe("🔍");
  });
});

describe("tokensPerSecLabel", () => {
  test("empty when there is no speed", () => {
    expect(tokensPerSecLabel({ tokens_per_sec: null })).toBe("");
  });

  test("a local model is rounded", () => {
    expect(tokensPerSecLabel({ tokens_per_sec: 74.6, model_used: "gemma4" })).toBe("75 t/s");
  });

  test("cloud models get a ~ prefix (the measurement includes prompt + network)", () => {
    expect(tokensPerSecLabel({ tokens_per_sec: 20.2, model_used: "glm-5.2:cloud" })).toBe("~20 t/s");
  });
});
