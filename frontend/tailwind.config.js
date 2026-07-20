/** @type {import('tailwindcss').Config} */

// The neutral palette is bound to CSS variables (light/dark values live in index.css).
// That makes ALL existing classes (bg-neutral-900, text-neutral-200, …) theme-aware without
// touching a single component.
const n = (v) => `rgb(var(${v}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  // The `dark:` variant applies under an <html> carrying data-theme="dark" (used by a few accents).
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        neutral: {
          50: n("--n-50"),
          100: n("--n-100"),
          200: n("--n-200"),
          300: n("--n-300"),
          400: n("--n-400"),
          500: n("--n-500"),
          600: n("--n-600"),
          700: n("--n-700"),
          800: n("--n-800"),
          900: n("--n-900"),
          950: n("--n-950"),
        },
        // Accent (data-accent + index.css). The DEFAULT triplet supports alpha (bg-accent/25);
        // hover/text are theme-aware color-mix full colours (no alpha).
        accent: {
          DEFAULT: n("--accent"),
          hover: "var(--accent-hover)",
          text: "var(--accent-text)",
        },
      },
    },
  },
  plugins: [],
};
