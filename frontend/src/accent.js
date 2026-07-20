// Accent colour store (same pattern as theme.js). The data-accent attribute is written on <html>;
// index.css swaps the --accent variable, and hover/link shades are derived with color-mix.
// The 9 accent colours of GNOME 47+ Adwaita. Default: Adwaita blue.
import { useSyncExternalStore } from "react";

const ACCENT_KEY = "calivi_accent";

// key = the data-accent value; hex = the swatch colour in settings (same as the triplet in index.css).
export const ACCENTS = [
  { key: "blue", hex: "#3584e4" },
  { key: "teal", hex: "#2190a4" },
  { key: "green", hex: "#3a944a" },
  { key: "yellow", hex: "#c88800" },
  { key: "orange", hex: "#ed5b00" },
  { key: "red", hex: "#e62d42" },
  { key: "pink", hex: "#d56199" },
  { key: "purple", hex: "#9141ac" },
  { key: "slate", hex: "#6f8396" },
];

const KEYS = ACCENTS.map((a) => a.key);

let current = (() => {
  const stored = localStorage.getItem(ACCENT_KEY);
  return KEYS.includes(stored) ? stored : "blue";
})();

const listeners = new Set();

function apply(accent) {
  document.documentElement.setAttribute("data-accent", accent);
}
apply(current);

export function getAccent() {
  return current;
}

export function setAccent(accent) {
  if (!KEYS.includes(accent) || accent === current) return;
  current = accent;
  localStorage.setItem(ACCENT_KEY, accent);
  apply(accent);
  listeners.forEach((l) => l());
}

function subscribe(cb) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

export function useAccent() {
  return useSyncExternalStore(subscribe, getAccent);
}
