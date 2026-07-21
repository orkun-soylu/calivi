import { render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import MessageItem from "./MessageItem.jsx";

// Markdown is heavy (react-markdown + KaTeX) and is not what is under test here.
vi.mock("../Markdown.jsx", () => ({
  default: ({ content }) => <div data-testid="markdown">{content}</div>,
}));

const noop = () => {};

function draw(m) {
  return render(<MessageItem m={m} onEdit={noop} onDelete={noop} onImageClick={noop} />);
}

const assistant = {
  role: "assistant",
  content: "answer",
  model_used: "gemma4",
  server_used: "local-gpu",
  timestamp: "2026-07-19T10:00:00",
};

describe("MessageItem", () => {
  test("assistant content goes through Markdown", () => {
    draw(assistant);
    expect(screen.getByTestId("markdown").textContent).toBe("answer");
  });

  test("user content does NOT go through Markdown (raw text is preserved)", () => {
    draw({ role: "user", content: "**raw**", timestamp: assistant.timestamp });
    expect(screen.queryByTestId("markdown")).toBeNull();
    expect(screen.getByText("**raw**")).toBeTruthy();
  });

  test("the assistant header shows model · server", () => {
    draw(assistant);
    expect(screen.getByText("gemma4 · local-gpu")).toBeTruthy();
  });

  test("without model_used the assistant footer is not rendered at all", () => {
    // On partial/old records model_used can be empty; copy/delete were not shown in that case either.
    const { container } = draw({ role: "assistant", content: "x", timestamp: assistant.timestamp });
    expect(container.querySelectorAll("button")).toHaveLength(0);
  });

  test("with model_used the copy + delete buttons are rendered", () => {
    const { container } = draw(assistant);
    expect(container.querySelectorAll("button")).toHaveLength(2);
  });

  test("a user message renders copy + edit + delete (3 buttons)", () => {
    const { container } = draw({ role: "user", content: "question", timestamp: assistant.timestamp });
    expect(container.querySelectorAll("button")).toHaveLength(3);
  });

  test("with tokens_per_sec the generation speed is shown", () => {
    draw({ ...assistant, tokens_per_sec: 74.6 });
    expect(screen.getByText("75 t/s")).toBeTruthy();
  });

  test("without tokens_per_sec the speed field stays empty", () => {
    draw(assistant);
    expect(screen.queryByText(/t\/s/)).toBeNull();
  });

  test("clicking an image calls the lightbox callback", () => {
    const onImageClick = vi.fn();
    const { container } = render(
      <MessageItem
        m={{ ...assistant, role: "user", images: ["data:image/png;base64,AAA"] }}
        onEdit={noop}
        onDelete={noop}
        onImageClick={onImageClick}
      />
    );
    container.querySelector("img").click();
    expect(onImageClick).toHaveBeenCalledWith("data:image/png;base64,AAA");
  });

  test("attachment chips are listed with the file name", () => {
    draw({ ...assistant, role: "user", attachments: [{ name: "report.pdf" }] });
    expect(screen.getByText("report.pdf")).toBeTruthy();
  });
});

describe("tool output chips", () => {
  const withChips = {
    role: "user",
    content: "question",
    timestamp: "2026-07-21T17:54:09",
    attachments: [
      { name: "🔧 context7: query-docs", detail: "WHAT THE TOOL RETURNED" },
      { name: "📎 notes.pdf" },
    ],
  };

  test("a chip carrying tool output opens it on click", async () => {
    const onInspect = vi.fn();
    render(
      <MessageItem m={withChips} onEdit={noop} onDelete={noop} onImageClick={noop} onInspect={onInspect} />
    );

    screen.getByText("🔧 context7: query-docs").click();

    expect(onInspect).toHaveBeenCalledWith({
      name: "🔧 context7: query-docs",
      detail: "WHAT THE TOOL RETURNED",
    });
  });

  test("a plain document chip stays inert", () => {
    const onInspect = vi.fn();
    render(
      <MessageItem m={withChips} onEdit={noop} onDelete={noop} onImageClick={noop} onInspect={onInspect} />
    );

    screen.getByText("📎 notes.pdf").click();

    expect(onInspect).not.toHaveBeenCalled();
  });
});
