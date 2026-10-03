import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import ApprovalCard from "./ApprovalCard.jsx";
import { setLang } from "../../i18n.js";

beforeEach(() => setLang("en"));

const call = { id: "p1", name: "bash", args: { command: "sudo systemctl stop ollama" } };

test("no suggestion, no Always allow", () => {
  render(<ApprovalCard approval={call} onDecide={vi.fn()} />);
  expect(screen.queryByText("Always allow…")).toBeNull();
});

test("Always allow sends the edited rule with the yes", async () => {
  const onDecide = vi.fn(async () => {});
  render(
    <ApprovalCard
      approval={{ ...call, rule_suggestion: { kind: "exact", pattern: "sudo systemctl stop ollama" } }}
      onDecide={onDecide}
    />
  );
  fireEvent.click(screen.getByText("Always allow…"));
  fireEvent.change(screen.getByLabelText("Rule type"), { target: { value: "prefix" } });
  fireEvent.change(screen.getByLabelText("Rule"), { target: { value: "sudo systemctl stop" } });
  fireEvent.click(screen.getByText("Save rule and approve"));
  await waitFor(() =>
    expect(onDecide).toHaveBeenCalledWith("p1", true, { kind: "prefix", pattern: "sudo systemctl stop" })
  );
});

test("a refused rule shows the backend's reason and the card stays", async () => {
  const onDecide = vi.fn(async () => {
    throw new Error('400 {"detail":"this rule does not cover the call on the card"}');
  });
  render(
    <ApprovalCard
      approval={{ ...call, rule_suggestion: { kind: "exact", pattern: "sudo systemctl stop ollama" } }}
      onDecide={onDecide}
    />
  );
  fireEvent.click(screen.getByText("Always allow…"));
  fireEvent.click(screen.getByText("Save rule and approve"));
  expect(await screen.findByText("this rule does not cover the call on the card")).toBeTruthy();
  expect(screen.getByText("Save rule and approve")).toBeTruthy();
});
