import { describe, expect, test } from "vitest";
import { LANGUAGES, translations } from "./i18n.js";

// A key missing from a language does not fail loudly: `translate` falls back to Turkish. So 43
// keys (Settings → General, the sign-in screen, user management) went unnoticed in seven
// languages until 0.3.x. This makes the next gap a test failure instead.
const base = Object.keys(translations.tr);
const vars = (s) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe("translations", () => {
  test("every language in the picker has a table", () => {
    expect(Object.keys(translations).sort()).toEqual(LANGUAGES.map((l) => l.code).sort());
  });

  test.each(Object.keys(translations))("%s has exactly the Turkish keys", (lang) => {
    const keys = Object.keys(translations[lang]);
    expect(base.filter((k) => !keys.includes(k))).toEqual([]);
    expect(keys.filter((k) => !base.includes(k))).toEqual([]);
  });

  test.each(Object.keys(translations))("%s has no empty text and keeps every {variable}", (lang) => {
    for (const k of base) {
      const text = translations[lang][k];
      expect(typeof text === "string" && text.trim().length > 0, `${lang} ${k}`).toBe(true);
      expect(vars(text), `${lang} ${k}`).toEqual(vars(translations.tr[k]));
    }
  });
});
