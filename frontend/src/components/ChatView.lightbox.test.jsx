import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, expect, test, vi, beforeEach } from "vitest";
import ChatView from "./ChatView.jsx";

// Markdown is heavy (react-markdown + KaTeX) and is not what is under test here.
vi.mock("./Markdown.jsx", () => ({
  default: ({ content }) => <div data-testid="markdown">{content}</div>,
}));

// ChatView reads the server/model preference on mount; it must never reach the network layer.
vi.mock("../api.js", () => ({
  api: {
    sendMessage: vi.fn(),
    getChat: vi.fn(),
    deleteMessage: vi.fn(),
  },
  setUnauthorizedHandler: vi.fn(),
}));

const IMG = "data:image/png;base64,AAA";

const servers = [
  {
    id: 1,
    name: "s1",
    status: "up",
    models: ["m1"],
    vision_models: ["m1"],
  },
];

const chat = {
  id: 1,
  messages: [{ id: 10, role: "user", content: "look", images: [IMG], timestamp: "2026-07-20T10:00:00" }],
};

function draw() {
  return render(
    <ChatView
      chat={chat}
      servers={servers}
      onMessageSent={() => {}}
      onForked={() => {}}
      onOpenSettings={() => {}}
    />
  );
}

/** Find the overlay by its class (it has no role/text — it is purely a visual layer). */
function overlay(container) {
  return container.querySelector(".fixed.inset-0");
}

beforeEach(() => {
  localStorage.clear();
  // jsdom does not implement scrollIntoView; MessageList calls it on every render.
  Element.prototype.scrollIntoView = vi.fn();
});

describe("lightbox", () => {
  test("opens when an image is clicked", () => {
    const { container } = draw();
    expect(overlay(container)).toBeNull();

    fireEvent.click(screen.getAllByRole("presentation", { hidden: true })[0] ?? container.querySelector("img"));
    expect(overlay(container)).not.toBeNull();
  });

  test("closes when the overlay is clicked", () => {
    const { container } = draw();
    fireEvent.click(container.querySelector("img"));
    expect(overlay(container)).not.toBeNull();

    fireEvent.click(overlay(container));
    expect(overlay(container)).toBeNull();
  });

  test("Esc closes the lightbox", () => {
    const { container } = draw();
    fireEvent.click(container.querySelector("img"));
    expect(overlay(container)).not.toBeNull();

    act(() => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    expect(overlay(container)).toBeNull();
  });

  test("Esc does NOT stop the stream while the lightbox is open", () => {
    // The actual regression: useChatStream also binds Escape on window. With the lightbox open,
    // pressing Esc cancelled the in-flight answer (the user only wanted to close the overlay).
    // capture:true + stopPropagation must prevent that.
    const stopKey = vi.fn();
    window.addEventListener("keydown", stopKey); // same phase as useChatStream's listener

    const { container } = draw();
    fireEvent.click(container.querySelector("img"));

    act(() => {
      fireEvent.keyDown(window, { key: "Escape" });
    });

    expect(overlay(container)).toBeNull(); // the lightbox closed
    expect(stopKey).not.toHaveBeenCalled(); // it NEVER reached the bubble listener
    window.removeEventListener("keydown", stopKey);
  });

  test("with the lightbox closed, Esc reaches the bubble listener", () => {
    // The reverse direction: the capture listener must not swallow Esc while the lightbox is
    // closed, otherwise cancelling the stream with Esc would break.
    const stopKey = vi.fn();
    window.addEventListener("keydown", stopKey);

    draw();
    act(() => {
      fireEvent.keyDown(window, { key: "Escape" });
    });

    expect(stopKey).toHaveBeenCalled();
    window.removeEventListener("keydown", stopKey);
  });
});
