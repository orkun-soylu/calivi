import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    // Never inline fonts as data: URIs. Vite inlines assets under 4 KB, which caught one KaTeX
    // font (KaTeX_Size3); nginx's CSP has `font-src 'self'`, so the browser refused it.
    // Keeping the CSP strict and the font a file is the fix, not `data:` in font-src.
    assetsInlineLimit: (file) => (/\.(woff2?|ttf|otf|eot)$/.test(file) ? false : undefined),
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
