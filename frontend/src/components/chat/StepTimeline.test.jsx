import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import StepTimeline from "./StepTimeline.jsx";
import { setLang } from "../../i18n.js";

vi.mock("../Markdown.jsx", () => ({ default: ({ content }) => <div data-testid="md">{content}</div> }));

setLang("en");

const hostile = '<img src=x onerror="alert(1)"> **bold** [link](http://evil)';
const items = [
  { kind: "text", text: "Checking the service." },
  { kind: "call", name: "bash", args: { command: "systemctl status ollama" }, status: "ok", output: hostile },
];

describe("StepTimeline", () => {
  test("shows the command; the output only on demand", () => {
    render(<StepTimeline items={items} />);
    expect(screen.getByText("systemctl status ollama")).toBeTruthy();
    expect(screen.queryByText(hostile)).toBeNull();
    fireEvent.click(screen.getByRole("button", { expanded: false }));
    expect(screen.getByText(hostile)).toBeTruthy();
  });

  test("tool output is plain text — never markup", () => {
    const { container } = render(<StepTimeline items={items} />);
    fireEvent.click(screen.getByRole("button", { expanded: false }));
    // In a <pre> itself — the Markdown mock would render a hostile string as text too, so the
    // element is what proves no markup pipeline was involved.
    expect(screen.getByText(hostile).tagName).toBe("PRE");
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("strong")).toBeNull();
    // The model's own words between steps do go through Markdown, like a reply's content.
    expect(screen.getByTestId("md").textContent).toBe("Checking the service.");
  });

  test("the approval card renders in the row that is waiting", () => {
    const waiting = [{ kind: "call", name: "bash", args: { command: "rm -rf /tmp/x" }, status: "running", output: "", awaiting: true }];
    const onDecide = vi.fn();
    render(<StepTimeline items={waiting} approval={{ id: "p1", name: "bash", args: { command: "rm -rf /tmp/x" } }} onDecide={onDecide} />);
    fireEvent.click(screen.getByText("Approve"));
    expect(onDecide).toHaveBeenCalledWith("p1", true);
  });
});
