import { beforeEach, describe, expect, test } from "vitest";
import { IMAGE_OPTIONS_KEY, imageOptionsPayload, loadImageOptions, saveImageOptions } from "./imageOptions.js";

beforeEach(() => localStorage.clear());

describe("imageOptionsPayload", () => {
  test("defaults send nothing", () => {
    expect(imageOptionsPayload({ size: "", steps: "", seed: "" })).toEqual({});
    expect(imageOptionsPayload()).toEqual({});
  });

  test("set values go out, steps and seed as numbers", () => {
    expect(imageOptionsPayload({ size: "1664x928", steps: "20", seed: "674579909" })).toEqual({
      size: "1664x928", steps: 20, seed: 674579909,
    });
  });

  test("a seed of 0 is a seed, not 'random'", () => {
    expect(imageOptionsPayload({ seed: "0" })).toEqual({ seed: 0 });
  });

  test("a half-typed or junk seed is left out rather than sent", () => {
    expect(imageOptionsPayload({ seed: " " })).toEqual({});
    expect(imageOptionsPayload({ seed: "12a" })).toEqual({});
  });
});

describe("remembering", () => {
  test("size and steps are remembered, the seed is not", () => {
    saveImageOptions({ size: "1024x1536", steps: "20", seed: "5" });
    expect(JSON.parse(localStorage.getItem(IMAGE_OPTIONS_KEY))).toEqual({ size: "1024x1536", steps: "20" });
    expect(loadImageOptions()).toEqual({ size: "1024x1536", steps: "20", seed: "" });
  });

  test("a broken stored value falls back to the defaults", () => {
    localStorage.setItem(IMAGE_OPTIONS_KEY, "{not json");
    expect(loadImageOptions()).toEqual({ size: "", steps: "", seed: "" });
  });
});
