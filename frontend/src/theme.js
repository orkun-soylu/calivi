// Lightweight theme store (same pattern as i18n.js): module-level + useSyncExternalStore.
// The data-theme attribute is written on <html>; CSS variables (index.css) swap the neutral palette.
// Default: the system preference (prefers-color-scheme) when localStorage is empty. Persisted once
// the user switches.
import { useSyncExternalStore } from "react";

const THEME_KEY = "calivi_theme";

function systemTheme() {
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

// The inline script in index.html already set data-theme early (to avoid a flash);
// here we stay in sync using the same logic.
let current = (() => {
  const stored = localStorage.getItem(THEME_KEY);
  return stored === "light" || stored === "dark" ? stored : systemTheme();
})();

const listeners = new Set();

function apply(theme) {
  document.documentElement.setAttribute("data-theme", theme);
}
apply(current);

export function getTheme() {
  return current;
}

export function setTheme(theme) {
  if (theme !== "light" && theme !== "dark") return;
  if (theme === current) return;
  current = theme;
  localStorage.setItem(THEME_KEY, theme);
  apply(theme);
  listeners.forEach((l) => l());
}

function subscribe(cb) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

export function useTheme() {
  return useSyncExternalStore(subscribe, getTheme);
}
