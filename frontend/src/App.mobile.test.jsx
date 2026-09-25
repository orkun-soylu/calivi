import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import App from "./App.jsx";
import { setLang } from "./i18n.js";

vi.mock("./components/Markdown.jsx", () => ({
  default: ({ content }) => <div>{content}</div>,
}));

const chat = {
  id: 7,
  title: "Kyoto trip",
  pinned: false,
  messages: [{ id: 1, role: "user", content: "hello kyoto", timestamp: "2026-09-26T10:00:00" }],
};

vi.mock("./api.js", () => ({
  api: {
    getAuthConfig: vi.fn(async () => ({ registration_enabled: false })),
    getMe: vi.fn(async () => ({ id: 1, username: "u", role: "user" })),
    listChats: vi.fn(async () => [{ id: 7, title: "Kyoto trip", pinned: false }]),
    listServers: vi.fn(async () => []),
    getChat: vi.fn(async () => chat),
  },
  setUnauthorizedHandler: vi.fn(),
}));

/** A matchMedia whose answer the test controls. jsdom has none. */
function mockViewport(mobile) {
  window.matchMedia = (q) => ({
    matches: mobile,
    media: q,
    addEventListener: () => {},
    removeEventListener: () => {},
  });
}

beforeEach(() => {
  setLang("en");
  localStorage.clear();
  window.history.replaceState(null, "");
});

afterEach(() => {
  delete window.matchMedia;
});

describe("phone layout (#61)", () => {
  test("shows only the chat list until a chat is opened", async () => {
    mockViewport(true);
    render(<App />);
    await screen.findByText("Kyoto trip");
    expect(screen.queryByPlaceholderText("Type a message...")).toBeNull();

    fireEvent.click(screen.getByText("Kyoto trip"));
    await screen.findByText("hello kyoto");
    // The list is gone: the open chat has the whole screen.
    expect(screen.queryByText("Kyoto trip")).toBeNull();
    expect(screen.getByPlaceholderText("Type a message...")).toBeTruthy();
  });

  test("the back button returns to the list", async () => {
    mockViewport(true);
    render(<App />);
    fireEvent.click(await screen.findByText("Kyoto trip"));
    await screen.findByText("hello kyoto");

    // history.back() is async in jsdom; fire the popstate it would produce.
    const back = vi.spyOn(window.history, "back").mockImplementation(() => {
      window.history.replaceState(null, "");
      window.dispatchEvent(new PopStateEvent("popstate", { state: null }));
    });
    await act(async () => fireEvent.click(screen.getByTitle("Back to chats")));
    expect(back).toHaveBeenCalledOnce();
    await screen.findByText("Kyoto trip");
    expect(screen.queryByText("hello kyoto")).toBeNull();
  });

  test("the device back gesture returns to the list instead of leaving the app", async () => {
    mockViewport(true);
    render(<App />);
    fireEvent.click(await screen.findByText("Kyoto trip"));
    await screen.findByText("hello kyoto");
    expect(window.history.state).toEqual({ caliviChat: 7 });

    await act(async () => {
      window.history.replaceState(null, "");
      window.dispatchEvent(new PopStateEvent("popstate", { state: null }));
    });
    await screen.findByText("Kyoto trip");
  });

  test("desktop keeps list and chat side by side, with no back button", async () => {
    mockViewport(false);
    render(<App />);
    fireEvent.click(await screen.findByText("Kyoto trip"));
    await screen.findByText("hello kyoto");
    expect(screen.getByText("Kyoto trip")).toBeTruthy();
    expect(screen.queryByTitle("Back to chats")).toBeNull();
    await waitFor(() => expect(window.history.state).toBeNull());
  });
});
