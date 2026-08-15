import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `build.outDir` points at the Python package's own static-assets
// directory (`inst/python/deckifyr/web/app.py` mounts `<package>/static`
// as the served frontend) -- the built output is committed to git, the
// same "generated output ships in the repo" precedent `man/figures/*.png`
// already sets (CLAUDE.md), since neither the wheel nor the R package can
// run a Node build at install time.
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    outDir: "../inst/python/deckifyr/web/static",
    emptyOutDir: true,
  },
});
