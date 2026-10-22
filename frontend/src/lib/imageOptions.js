// The 🎨 picker's settings for image-generation models: size, steps, seed.
// "" means "the server's default" — nothing is sent for it (OpenAI rejects parameters it does not
// know, and steps / seed are not in its API).

export const IMAGE_SIZES = [
  // [value, i18n key]. The first three are also gpt-image's sizes; 16:9 / 9:16 are Qwen-Image's.
  ["1024x1024", "image.square"],
  ["1536x1024", "image.landscape"],
  ["1024x1536", "image.portrait"],
  ["1664x928", "image.wide"],
  ["928x1664", "image.tall"],
];

export const IMAGE_STEPS = [10, 20, 30, 40, 50];

export const IMAGE_OPTIONS_KEY = "calivi_image_options";

/** Size and steps are remembered; the seed is not, so a forgotten one cannot keep repeating a picture. */
export function loadImageOptions() {
  try {
    const saved = JSON.parse(localStorage.getItem(IMAGE_OPTIONS_KEY) || "{}");
    return { size: String(saved.size || ""), steps: String(saved.steps || ""), seed: "" };
  } catch {
    return { size: "", steps: "", seed: "" };
  }
}

export function saveImageOptions({ size, steps }) {
  localStorage.setItem(IMAGE_OPTIONS_KEY, JSON.stringify({ size, steps }));
}

/** The request body's `image_options`: only what is set, as numbers where the API wants them. */
export function imageOptionsPayload({ size, steps, seed } = {}) {
  const out = {};
  if (size) out.size = size;
  if (steps) out.steps = Number(steps);
  const s = String(seed ?? "").trim();
  if (/^\d+$/.test(s)) out.seed = Number(s);
  return out;
}
