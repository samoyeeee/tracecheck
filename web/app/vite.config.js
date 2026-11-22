import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

// Built into web/site, which both `python -m web.serve` and static hosting serve.
export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: { outDir: "../site", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
