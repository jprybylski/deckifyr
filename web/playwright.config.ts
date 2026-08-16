import { defineConfig, devices } from "@playwright/test";

/**
 * A real, third tier of frontend testing alongside `vitest` (mocked
 * fetch, jsdom -- fast, but structurally can't observe real browser
 * behavior like `beforeunload` dialogs) and the quarto/soffice-gated
 * `tests/python` integration tests (real external binaries, same
 * "skip cleanly when the toolchain is absent" posture CLAUDE.md already
 * documents for those -- see this config's own `webServer` below, which
 * needs `uv` on PATH the same way).
 *
 * `webServer` execs `e2e/serve-fixture.py` (not `deckifyr serve`
 * directly) so each run gets a fresh scratch copy of
 * `inst/examples/minimal-deck` -- these tests PATCH/discard real
 * project state, and the tracked fixture is shared with
 * `tests/python`/`tests/testthat`.
 */
const PORT = process.env.DECKIFYR_E2E_PORT ?? "8399";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  // All spec files share one `deckifyr serve` process/project (one
  // scratch copy per whole run, not per file -- see `serve-fixture.py`)
  // and mutate its real in-memory working copy (Config Apply, furniture
  // Add/Remove, ...). Running spec files concurrently lets one file's
  // leftover dirty state bleed into another's -- confirmed the hard
  // way: `build.spec.ts`'s "disabled while dirty" test left the project
  // dirty, which then made unrelated tests in other files fail their
  // own "All changes saved" starting-state assertion. Each spec file's
  // own `beforeEach` also discards before every test as a second,
  // file-level safeguard against a prior *test* (not just a prior
  // *file*) leaving dirty state behind.
  workers: 1,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `python3 e2e/serve-fixture.py`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 30_000,
    env: { DECKIFYR_E2E_PORT: PORT },
    stdout: "pipe",
    stderr: "pipe",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
