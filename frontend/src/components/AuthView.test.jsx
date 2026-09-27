import { render, fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import AuthView from "./AuthView.jsx";
import { api } from "../api.js";
import { setLang } from "../i18n.js";

setLang("en");

vi.mock("../api.js", () => ({ api: { register: vi.fn(), login: vi.fn() } }));

beforeEach(() => {
  api.register.mockReset().mockResolvedValue({ id: 1 });
});

const code = () => screen.queryByPlaceholderText(/Setup code/);

describe("AuthView — claiming an appliance", () => {
  test("a normal install asks for nothing extra", async () => {
    const { container } = render(<AuthView registrationEnabled onAuthed={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Sign up" }));
    expect(code()).toBeNull();
    fireEvent.change(screen.getByPlaceholderText("Username"), { target: { value: "u" } });
    fireEvent.submit(container.querySelector("form"));
    await waitFor(() => expect(api.register).toHaveBeenCalled());
    expect(api.register.mock.calls[0][0]).not.toHaveProperty("setup_code");
  });

  test("host setup opens on sign-up and sends the code and machine settings", async () => {
    const { container } = render(<AuthView registrationEnabled hostSetup onAuthed={() => {}} />);
    expect(code()).not.toBeNull();
    expect(screen.getByText(/Linux administrator/)).toBeTruthy();
    fireEvent.change(code(), { target: { value: "abcd-efgh" } });
    fireEvent.change(screen.getByPlaceholderText("Username"), { target: { value: "owner" } });
    fireEvent.change(screen.getByPlaceholderText(/Hostname/), { target: { value: "calivi-vm" } });
    fireEvent.submit(container.querySelector("form"));
    await waitFor(() => expect(api.register).toHaveBeenCalled());
    expect(api.register.mock.calls[0][0]).toMatchObject({
      username: "owner", setup_code: "abcd-efgh", hostname: "calivi-vm",
    });
  });
});
