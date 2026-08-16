import { test, expect } from "@playwright/test";

/**
 * Real-browser coverage for the deferred-save Save/Discard flow
 * (`SessionControls.tsx`, issue #24): clicking Discard calls
 * `window.location.reload()` right after clearing dirty state, and that
 * reload must not itself trigger the app's own `beforeunload` "unsaved
 * changes" confirmation -- a real, Playwright-confirmed regression this
 * test guards (see `dirtyRef`'s own comment in `SessionControls.tsx`).
 * `vitest`'s jsdom environment can't observe this either way; it doesn't
 * implement `beforeunload` blocking navigation the way a real browser
 * does, so this needs an actual browser, not a mock.
 *
 * `dialog.accept()` below mirrors what a real user does reflexively if
 * this regresses (the dialog is a real one, most people click through
 * it without a second thought) -- the test still fails via the final
 * `dialogAppeared` assertion, it just doesn't hang waiting for a dialog
 * nothing answers.
 */

test.beforeEach(async ({ page }) => {
  // A clean slate regardless of what a prior test in this or another
  // file left dirty (see playwright.config.ts's own `workers: 1`
  // comment for the full reasoning) -- load-bearing here specifically,
  // since this test's own first assertion depends on starting clean.
  await page.request.post("/api/discard");
});

test("discarding an edit reverts it, with no blocking confirmation dialog", async ({ page }) => {
  let dialogAppeared = false;
  page.on("dialog", async (dialog) => {
    dialogAppeared = true;
    console.log(`unexpected ${dialog.type()} dialog: ${JSON.stringify(dialog.message())}`);
    await dialog.accept();
  });

  await page.goto("/");
  await expect(page.getByText("All changes saved")).toBeVisible();

  // Select the title slide's `deck-title` markdown element by clicking
  // its rendered position on the Konva canvas (box: x=0.9in, y=2.1in,
  // width=11.5in, height=1.1in per inst/examples/minimal-deck/
  // presentation.yaml -- 96px/in at the toolbar's default 100% zoom,
  // see web/src/geometry.ts's own PIXELS_PER_INCH).
  const canvas = page.locator(".slide-canvas__stage-wrap canvas").first();
  await canvas.click({ position: { x: (0.9 + 11.5 / 2) * 96, y: (2.1 + 1.1 / 2) * 96 } });

  const xInput = page.getByLabel("X (in)");
  await expect(xInput).toHaveValue("0.9000");

  // Edit via the properties panel (real DOM input + button) rather than
  // a simulated canvas drag gesture -- both paths PATCH the same
  // endpoint and drive the same dirty/discard state machine this test
  // actually cares about; the panel path is far less brittle to write
  // and maintain than a pixel-accurate Konva drag sequence.
  await xInput.fill("2.5000");
  await page.getByRole("button", { name: "Apply" }).click();

  await expect(page.getByText("Unsaved changes")).toBeVisible();
  await expect(xInput).toHaveValue("2.5000");

  await page.getByRole("button", { name: "Discard" }).click();

  // The real assertion: Discard must actually complete (a fresh page
  // load, dirty cleared) within a normal timeout -- not hang forever
  // behind an unanswered confirmation dialog the way the claude-in-chrome
  // reproduction appeared to. `handleDiscard` reloads the page on
  // success, so the prior selection is gone; re-select and check the
  // server-side value actually reverted, rather than trusting a stale
  // client-side field.
  await expect(page.getByText("All changes saved")).toBeVisible();
  await canvas.click({ position: { x: (0.9 + 11.5 / 2) * 96, y: (2.1 + 1.1 / 2) * 96 } });
  await expect(page.getByLabel("X (in)")).toHaveValue("0.9000");

  expect(dialogAppeared).toBe(false);
});
