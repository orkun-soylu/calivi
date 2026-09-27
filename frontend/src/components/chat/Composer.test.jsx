import { render, fireEvent, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import Composer from "./Composer.jsx";
import { setLang } from "../../i18n.js";

setLang("en");

function composer(props = {}) {
  const onToggleAskEveryTool = vi.fn();
  render(
    <Composer
      input=""
      onInputChange={() => {}}
      onSend={() => {}}
      onStop={() => {}}
      sending={false}
      canSend={false}
      images={[]}
      onRemoveImage={() => {}}
      attachments={[]}
      onRemoveAttachment={() => {}}
      onFiles={() => {}}
      onPaste={() => {}}
      useTools
      onToggleUseTools={() => {}}
      onToggleAskEveryTool={onToggleAskEveryTool}
      {...props}
    />
  );
  return onToggleAskEveryTool;
}

const toggle = () => screen.queryByTitle(/Every tool call waits|Only risky tool calls/);

describe("Composer — ask before every tool", () => {
  test("is absent where the model cannot operate the host", () => {
    composer({ hostTools: false });
    expect(toggle()).toBeNull();
  });

  test("shows its state and toggles when the host tools are available", () => {
    const onToggle = composer({ hostTools: true, askEveryTool: false });
    expect(toggle().getAttribute("aria-pressed")).toBe("false");
    expect(toggle().title).toMatch(/Only risky tool calls/);
    fireEvent.click(toggle());
    expect(onToggle).toHaveBeenCalledOnce();
  });

  test("on: says every call waits", () => {
    composer({ hostTools: true, askEveryTool: true });
    expect(toggle().getAttribute("aria-pressed")).toBe("true");
    expect(toggle().title).toMatch(/Every tool call waits/);
  });
});
