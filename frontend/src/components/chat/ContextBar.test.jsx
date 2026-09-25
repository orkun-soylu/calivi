import { render, fireEvent, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import ContextBar, { formatTokens } from "./ContextBar.jsx";
import MessageList from "./MessageList.jsx";
import { setLang } from "../../i18n.js";

vi.mock("../Markdown.jsx", () => ({
  default: ({ content }) => <div>{content}</div>,
}));

setLang("en");

function chat(over = {}) {
  return {
    id: 1,
    messages: [],
    summary: null,
    summary_upto_id: null,
    context_mode: "compact",
    context_tokens_estimate: 31450,
    compactable: true,
    compact_suggested: false,
    ...over,
  };
}

function bar(over = {}, handlers = {}) {
  const h = {
    onCompact: vi.fn(),
    onStopCompact: vi.fn(),
    onSetMode: vi.fn(),
    onViewSummary: vi.fn(),
    ...handlers,
  };
  const view = render(<ContextBar chat={chat(over)} compacting={over.compacting ?? null} {...h} />);
  return { view, h };
}

describe("ContextBar", () => {
  test("stays out of the way below the threshold with no summary", () => {
    const { view } = bar();
    expect(view.container.innerHTML).toBe("");
  });

  test("suggests, but only the user starts, compaction", () => {
    const { h } = bar({ compact_suggested: true });
    expect(screen.getByText(/about 31k tokens/)).toBeTruthy();
    expect(h.onCompact).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Compact"));
    expect(h.onCompact).toHaveBeenCalledOnce();
  });

  test("with a summary, switches between summary and full history", () => {
    const { h } = bar({ summary: "S", summary_upto_id: 4 });
    const full = screen.getByText("Full history");
    expect(screen.getByText("Summary + recent").getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(full);
    expect(h.onSetMode).toHaveBeenCalledWith("full");
    fireEvent.click(screen.getByText("View summary"));
    expect(h.onViewSummary).toHaveBeenCalledOnce();
  });

  test("shows progress and can be stopped while summarising", () => {
    const { h } = bar({ compacting: { chars: 120 } });
    expect(screen.getByText(/120 characters/)).toBeTruthy();
    fireEvent.click(screen.getByText("Stop"));
    expect(h.onStopCompact).toHaveBeenCalledOnce();
  });

  test("formats the estimate without false precision", () => {
    expect(formatTokens(850)).toBe("850");
    expect(formatTokens(31450)).toBe("31k");
  });
});

describe("MessageList summary divider", () => {
  const messages = [
    { id: 1, role: "user", content: "q1", timestamp: "2026-01-01T00:00:00Z" },
    { id: 2, role: "assistant", content: "a1", timestamp: "2026-01-01T00:00:00Z" },
    { id: 3, role: "user", content: "q2", timestamp: "2026-01-01T00:00:00Z" },
  ];
  const listProps = (c) => ({
    chat: c,
    edit: { editingId: null },
    upServers: [],
    stream: { streaming: "", thinking: "", sending: false, searchInfo: null, approval: null },
    pending: { user: null, images: [], attachments: [] },
    onImageClick: () => {},
    onStartEdit: () => {},
    onDeleteMessage: () => {},
    onDecide: () => {},
    onInspect: () => {},
  });
  const DIVIDER = /only sees the summary/;

  test("marks where the summarised part ends", () => {
    render(<MessageList {...listProps(chat({ messages, summary: "S", summary_upto_id: 2 }))} />);
    const divider = screen.getByText(DIVIDER);
    // Sits between answer 1 and question 2.
    const text = document.body.textContent;
    expect(text.indexOf("a1")).toBeLessThan(text.indexOf(divider.textContent));
    expect(text.indexOf(divider.textContent)).toBeLessThan(text.indexOf("q2"));
  });

  test("has no divider in full-history mode", () => {
    render(
      <MessageList {...listProps(chat({ messages, summary: "S", summary_upto_id: 2, context_mode: "full" }))} />
    );
    expect(screen.queryByText(DIVIDER)).toBeNull();
  });
});
