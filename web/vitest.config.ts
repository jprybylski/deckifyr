import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Separate from vite.config.ts (rather than merging test config into it)
// so `vite build`'s own config stays free of test-only settings/types --
// vitest picks this file up automatically ahead of vite.config.ts.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    // e2e/ holds Playwright specs (npm run test:e2e), a real-browser
    // tier vitest's jsdom environment can't run -- excluded here so
    // `npm test`'s default glob doesn't also try to collect them.
    exclude: ["**/node_modules/**", "./e2e/**"],
  },
});
