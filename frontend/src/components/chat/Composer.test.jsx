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

describe("Composer — image models (🎨)", () => {
  const opts = { size: "", steps: "", seed: "" };

  test("a chat model gets the tools button and no image settings", () => {
    composer({ imageModel: false, imageOptions: opts });
    expect(screen.queryByText("Size")).toBeNull();
    expect(screen.getByTitle(/Tools/)).toBeTruthy();
  });

  test("an image model gets size / steps / seed instead of the tools button", () => {
    composer({ imageModel: true, imageOptions: opts, onImageOptionsChange: () => {} });
    expect(screen.getByText("Size")).toBeTruthy();
    expect(screen.getByText("Steps")).toBeTruthy();
    expect(screen.getByPlaceholderText("random")).toBeTruthy();
    expect(screen.queryByTitle(/Tools/)).toBeNull();
  });

  test("changes report the whole settings object; the seed keeps digits only", () => {
    const onChange = vi.fn();
    composer({ imageModel: true, imageOptions: opts, onImageOptionsChange: onChange });
    fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: "1024x1536" } });
    expect(onChange).toHaveBeenLastCalledWith({ size: "1024x1536", steps: "", seed: "" });
    fireEvent.change(screen.getByPlaceholderText("random"), { target: { value: "12a3" } });
    expect(onChange).toHaveBeenLastCalledWith({ size: "", steps: "", seed: "123" });
  });
});
