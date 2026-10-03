import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import PlanCard from "./PlanCard.jsx";
import { setLang } from "../../i18n.js";

beforeEach(() => setLang("en"));

const plan = {
  summary: "Restart **Ollama**",
  steps: [
    { title: "Override", commands: [], files: ["/etc/systemd/system/ollama.service.d/ctx.conf"] },
    { title: "Restart", commands: ["sudo systemctl restart ollama", "<img src=x onerror=alert(1)>"], files: [] },
  ],
  risks: "A few seconds down.",
  rollback: "Delete the override.",
  status: "proposed",
};

test("commands are shown verbatim, as text", () => {
  render(<PlanCard plan={plan} actions={null} />);
  const pre = [...document.querySelectorAll("pre")].map((p) => p.textContent).join("\n");
  expect(pre).toContain("$ sudo systemctl restart ollama");
  expect(pre).toContain("file: /etc/systemd/system/ollama.service.d/ctx.conf");
  expect(pre).toContain("$ <img src=x onerror=alert(1)>");
  expect(document.querySelector("img")).toBeNull();
  expect(screen.getByText("Restart **Ollama**")).toBeTruthy(); // not markdown either
});

test("Run and Cancel only while it is proposed and decidable", async () => {
  const actions = { onRun: vi.fn(async () => {}), onCancel: vi.fn(async () => {}) };
  const { rerender } = render(<PlanCard plan={plan} actions={actions} />);
  fireEvent.click(screen.getByText("Run it"));
  await waitFor(() => expect(actions.onRun).toHaveBeenCalled());
  fireEvent.click(screen.getByText("Cancel"));
  await waitFor(() => expect(actions.onCancel).toHaveBeenCalled());

  rerender(<PlanCard plan={plan} actions={null} />); // no longer the chat's last word
  expect(screen.queryByText("Run it")).toBeNull();
  rerender(<PlanCard plan={{ ...plan, status: "approved" }} actions={actions} />);
  expect(screen.queryByText("Run it")).toBeNull();
  expect(screen.getByText("approved")).toBeTruthy();
});
