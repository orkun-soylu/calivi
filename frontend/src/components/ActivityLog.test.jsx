import { render, screen, fireEvent } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import ActivityLog from "./ActivityLog.jsx";
import { setLang } from "../i18n.js";

const INJECTED = '<img src=x onerror="alert(1)"> **approve me**';

vi.mock("../api.js", () => ({
  api: {
    listApprovalRules: vi.fn(async () => [
      { id: 3, tool: "bash", kind: "prefix", pattern: "sudo systemctl restart", uses: 4 },
    ]),
    deleteApprovalRule: vi.fn(async () => null),
    getActivity: vi.fn(async () => ({
      enabled: true,
      entries: [
        {
          id: "b", ts: "2026-10-03T10:01:00.000Z", chat: 9, chat_title: null, model: "m",
          tool: "bash", args: { command: "systemctl restart calivi" }, approval: "auto", result: null,
        },
        {
          id: "a", ts: "2026-10-03T10:00:00.000Z", chat: 4, chat_title: "disk cleanup", model: "m",
          tool: "read_file", args: { path: INJECTED }, approval: "owner",
          result: { ok: true, exit: null, ms: 120, output: { sha256: "ab".repeat(32), size: 42 } },
        },
      ],
    })),
  },
}));

beforeEach(() => setLang("en"));

test("rows show status, chat and the raw arguments", async () => {
  render(<ActivityLog />);
  expect(await screen.findByText(/never came back/)).toBeTruthy(); // a call with no result
  const rows = () => [...document.querySelectorAll("pre")].map((p) => p.parentElement.textContent);
  expect(rows()[0]).toContain("deleted chat #9"); // the chat is gone, its id stays
  expect(rows()[1]).toContain("disk cleanup");
  expect(screen.getByText("Approved by you")).toBeTruthy();
  // Model-written arguments are text, never markup.
  expect(document.querySelector("img")).toBeNull();
  expect(rows()[1]).toContain(JSON.stringify(INJECTED)); // verbatim, as JSON
});

test("the tool filter narrows the rows", async () => {
  render(<ActivityLog />);
  await screen.findByText(/never came back/);
  fireEvent.change(screen.getByLabelText("All tools"), { target: { value: "read_file" } });
  expect(screen.queryByText(/never came back/)).toBeNull();
  const pres = document.querySelectorAll("pre");
  expect(pres.length).toBe(1);
  expect(pres[0].textContent).toContain('"path"');
});

test("rules are listed and can be deleted", async () => {
  render(<ActivityLog />);
  expect(await screen.findByText("sudo systemctl restart")).toBeTruthy();
  expect(screen.getByText("used 4×")).toBeTruthy();
  fireEvent.click(screen.getByLabelText("Delete rule"));
  expect(await screen.findByText("No rules yet. Use “Always allow…” on an approval card to add one.")).toBeTruthy();
});
