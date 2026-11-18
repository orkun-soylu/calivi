import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import ApprovalCard from "./ApprovalCard.jsx";
import { setLang } from "../../i18n.js";

beforeEach(() => setLang("en"));

const call = { id: "p1", name: "mcp__github__create_issue", args: { title: "<b>hi</b>" } };

test("the arguments are shown as raw JSON in a <pre>, never rendered", () => {
  const { container } = render(<ApprovalCard approval={call} onDecide={vi.fn()} />);
  const pre = container.querySelector("pre");
  expect(pre.textContent).toContain('"title": "<b>hi</b>"');
  expect(container.querySelector("b")).toBeNull();
});

test("Approve and Deny send the decision", async () => {
  const onDecide = vi.fn(async () => {});
  render(<ApprovalCard approval={call} onDecide={onDecide} />);
  fireEvent.click(screen.getByText("Approve"));
  await waitFor(() => expect(onDecide).toHaveBeenCalledWith("p1", true));
  fireEvent.click(screen.getByText("Deny"));
  await waitFor(() => expect(onDecide).toHaveBeenCalledWith("p1", false));
});
