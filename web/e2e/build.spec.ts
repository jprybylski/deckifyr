import { test, expect } from "@playwright/test";

/** Real-browser coverage for the Build tab: `POST /api/build` runs a
 * real `deckifyr build` subprocess (`JobManager`, not an in-process
 * compose) against the fixture project and this polls it to
 * completion. The tab-nav button and the build-trigger button both say
 * "Build" -- every locator below is scoped to `.build-panel` once the
 * tab is open, to stay unambiguous. */

test.beforeEach(async ({ page }) => {
  // Each test gets a clean slate regardless of what a prior test in this
  // or another file left dirty (see playwright.config.ts's own
  // `workers: 1` comment for the full reasoning) -- load-bearing here
  // specifically, since the second test below deliberately leaves the
  // project dirty and never cleans up after itself.
  await page.request.post("/api/discard");
});

test("building the fixture project succeeds and lists a downloadable artifact", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("All changes saved")).toBeVisible();
  await page.getByRole("button", { name: "Build" }).click();

  const panel = page.locator(".build-panel");
  await panel.getByRole("button", { name: "Build" }).click();
  await expect(panel.getByText(/Status: (queued|running)/)).toBeVisible();
  await expect(panel.getByText("Status: succeeded")).toBeVisible({ timeout: 30_000 });

  await expect(panel.getByRole("link", { name: "pptx" })).toBeVisible();
});

test("Build is disabled while there are unsaved changes", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("All changes saved")).toBeVisible();

  await page.getByLabel("Deck status").fill("dirty-for-build-test");
  await page.getByLabel("Deck status").blur();
  await expect(page.getByText("Unsaved changes")).toBeVisible();

  await page.getByRole("button", { name: "Build" }).click();
  const panel = page.locator(".build-panel");
  await expect(panel.getByRole("button", { name: "Build" })).toBeDisabled();
  await expect(panel.getByText(/Save your changes before building/)).toBeVisible();
});

test("toggling the previews checkbox syncs build.previews to the working copy (issue #32)", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByText("All changes saved")).toBeVisible();
  await page.getByRole("button", { name: "Build" }).click();

  const panel = page.locator(".build-panel");
  const checkbox = panel.getByRole("checkbox", {
    name: "Render slide previews (PNG + PDF) with this build",
  });
  await expect(checkbox).not.toBeChecked();

  // Not `.check()` -- this is a controlled checkbox synced to a PUT
  // round trip, so it doesn't reflect "checked" synchronously with the
  // click the way `.check()`'s own post-condition expects.
  await checkbox.click();
  await expect(checkbox).toBeChecked();
  await expect(page.getByText("Unsaved changes")).toBeVisible();

  const doc = await (await page.request.get("/api/config/presentation")).json();
  expect(doc.build.previews).toBe(true);
});
