/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  // GitHub Pages serves the site under /<repo-name>/; set VITE_BASE in the deploy workflow.
  base: process.env.VITE_BASE ?? "/",
  plugins: [tailwindcss()],
  test: {
    environment: "jsdom",
    coverage: { include: ["src/**/*.ts"], exclude: ["src/main.ts", "src/map.ts", "src/data.ts", "src/test-fixtures.ts", "src/**/*.test.ts"] },
  },
});
