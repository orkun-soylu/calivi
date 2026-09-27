import { render, fireEvent } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import MessageList from "./MessageList.jsx";

// Markdown is heavy (react-markdown + KaTeX) and is not what is under test here.
vi.mock("../Markdown.jsx", () => ({
  default: ({ content }) => <div>{content}</div>,
}));

const CLIENT_HEIGHT = 500;

function props(over = {}) {
  return {
    chat: { id: 1, messages: [] },
    edit: { editingId: null },
    upServers: [],
    stream: { streaming: "", thinking: "", sending: true, searchInfo: null, approval: null },
    pending: { user: null, images: [], attachments: [] },
    onImageClick: () => {},
    onStartEdit: () => {},
    onDeleteMessage: () => {},
    onDecide: () => {},
    onInspect: () => {},
    ...over,
  };
}

/**
 * Renders the list mid-stream. jsdom has no layout, so the scroller gets a fake geometry whose
 * content height the test controls; `grow` simulates a longer answer arriving.
 */
function setup() {
  let current = props({ stream: { ...props().stream, streaming: "a" } });
  const view = render(<MessageList {...current} />);
  const el = view.container.querySelector(".themed-scroll");
  const geo = { scrollHeight: CLIENT_HEIGHT, scrollTop: 0 };
  Object.defineProperty(el, "clientHeight", { configurable: true, get: () => CLIENT_HEIGHT });
  Object.defineProperty(el, "scrollHeight", { configurable: true, get: () => geo.scrollHeight });
  Object.defineProperty(el, "scrollTop", {
    configurable: true,
    get: () => geo.scrollTop,
    set: (v) => {
      geo.scrollTop = Math.max(0, Math.min(v, geo.scrollHeight - CLIENT_HEIGHT));
    },
  });

  const rerender = (over) => {
    current = { ...current, ...over };
    view.rerender(<MessageList {...current} />);
  };
  const grow = (height, over = {}) => {
    geo.scrollHeight = height;
    rerender({ stream: { ...current.stream, streaming: current.stream.streaming + "x" }, ...over });
  };
  const userScrollsTo = (top) => {
    geo.scrollTop = top;
    fireEvent.scroll(el);
  };
  return { el, geo, grow, rerender, userScrollsTo, current: () => current };
}

describe("MessageList scroll following", () => {
  test("follows the bottom while streaming if the user has not scrolled", () => {
    const { geo, grow } = setup();
    grow(2000);
    expect(geo.scrollTop).toBe(2000 - CLIENT_HEIGHT);
    grow(3000);
    expect(geo.scrollTop).toBe(3000 - CLIENT_HEIGHT);
  });

  test("its own scroll does not switch following off when content grew before the event", () => {
    // Caught in a real browser, not by jsdom: the list scrolls itself to the end, a code block
    // lands before that scroll's event is delivered, and the gap then looked like the user leaving.
    const { el, geo, grow } = setup();
    grow(2000);
    geo.scrollHeight = 2600;
    fireEvent.scroll(el);
    grow(3000);
    expect(geo.scrollTop).toBe(3000 - CLIENT_HEIGHT);
  });

  test("stays where the user scrolled up to, while the answer keeps growing", () => {
    const { geo, grow, userScrollsTo } = setup();
    grow(2000);
    userScrollsTo(200);
    grow(3000);
    grow(4000);
    expect(geo.scrollTop).toBe(200);
  });

  test("resumes following once the user scrolls back to the bottom", () => {
    const { geo, grow, userScrollsTo } = setup();
    grow(2000);
    userScrollsTo(200);
    grow(3000);
    userScrollsTo(3000 - CLIENT_HEIGHT - 10); // within the threshold counts as the bottom
    grow(4000);
    expect(geo.scrollTop).toBe(4000 - CLIENT_HEIGHT);
  });

  test("sending a new message jumps back to the end", () => {
    const { geo, grow, userScrollsTo } = setup();
    grow(2000);
    userScrollsTo(100);
    grow(3000, { pending: { user: "next question", images: [], attachments: [] } });
    expect(geo.scrollTop).toBe(3000 - CLIENT_HEIGHT);
  });

  test("an answer finishing does not pull a reader back down", () => {
    const { geo, grow, rerender, userScrollsTo, current } = setup();
    rerender({ pending: { user: "q", images: [], attachments: [] } });
    grow(2000); // the list follows down first; scrolling up only counts as leaving from there
    userScrollsTo(0);
    geo.scrollHeight = 2500;
    // the stream ends: the saved messages arrive and the optimistic bubble clears
    rerender({
      chat: { ...current().chat, messages: [] },
      pending: { user: null, images: [], attachments: [] },
      stream: { ...current().stream, sending: false, streaming: "" },
    });
    expect(geo.scrollTop).toBe(0);
  });

  test("opening another chat starts at its end", () => {
    const { geo, grow, rerender, userScrollsTo } = setup();
    grow(2000);
    userScrollsTo(0);
    geo.scrollHeight = 2500;
    rerender({ chat: { id: 2, messages: [] } });
    expect(geo.scrollTop).toBe(2500 - CLIENT_HEIGHT);
  });
});

describe("agent mode (#91)", () => {
  const approval = { id: "p1", name: "bash", args: { command: "rm -rf /tmp/x" } };
  const waiting = [{ kind: "call", name: "bash", args: { command: "rm -rf /tmp/x" }, status: "running", output: "", awaiting: true }];

  test("the approval card is in the waiting step — and only there", () => {
    const view = render(<MessageList {...props({
      chat: { id: 1, mode: "agent", messages: [] },
      stream: { ...props().stream, approval, timeline: waiting, searchInfo: { status: "tool_running", name: "bash" } },
    })} />);
    expect(view.getAllByText("rm -rf /tmp/x", { exact: false }).length).toBeGreaterThan(0);
    // One card (in the row), no free-standing duplicate, and no chat-mode activity line.
    expect(view.container.querySelectorAll("pre").length).toBe(1);
    expect(view.queryByText(/bash/, { selector: ".text-xs.bg-neutral-900" })).toBeNull();
  });

  test("chat mode keeps the free-standing card", () => {
    const view = render(<MessageList {...props({ stream: { ...props().stream, approval, timeline: [] } })} />);
    expect(view.container.querySelectorAll("pre").length).toBe(1);
    expect(view.container.querySelector("button[aria-expanded]")).toBeNull();
  });

  test("a saved agent reply shows its steps before its answer", () => {
    const m = {
      id: 9, role: "assistant", content: "It is running.", model_used: "m", server_used: "s", timestamp: "2026-09-27T10:00:00",
      steps: [
        { role: "assistant", content: "", tool_calls: [{ id: "a", name: "bash", arguments: { command: "systemctl is-active ollama" } }] },
        { role: "tool", tool_call_id: "a", content: "active", ok: true, approval: null },
      ],
    };
    const view = render(<MessageList {...props({ chat: { id: 1, mode: "agent", messages: [m] }, stream: { ...props().stream, sending: false } })} />);
    const text = view.container.textContent;
    const step = text.indexOf("systemctl is-active ollama");
    expect(step).toBeGreaterThanOrEqual(0); // present at all — indexOf's -1 would pass the next line
    expect(step).toBeLessThan(text.indexOf("It is running."));
  });
});
