import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import ServerModelPicker from "./ServerModelPicker.jsx";

const servers = [
  { id: 8, name: "gpu-box", models: ["iq3_s-2gpu", "qwen-image-2.1"], image_models: ["qwen-image-2.1"] },
];

test("image models carry a marker, their value stays the bare name", () => {
  render(<ServerModelPicker servers={servers} value={{ serverId: 8, model: "qwen-image-2.1" }} onChange={() => {}} />);
  const image = screen.getByRole("option", { name: "🎨 qwen-image-2.1" });
  expect(image.value).toBe("qwen-image-2.1");
  expect(screen.getByRole("option", { name: "iq3_s-2gpu" })).toBeTruthy();
});

test("a server list without image_models (an older backend) still renders", () => {
  const old = [{ id: 1, name: "o", models: ["m"] }];
  render(<ServerModelPicker servers={old} value={{ serverId: 1, model: "m" }} onChange={() => {}} />);
  expect(screen.getByRole("option", { name: "m" })).toBeTruthy();
});
