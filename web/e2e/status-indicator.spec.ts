import { test, expect } from "@playwright/test";

/**
 * Real-browser coverage for the Status/watermark redesign (a strict
 * single-select `status_indicator`, one `__furniture_status` element --
 * see `deckifyr.plan.FURNITURE_STATUS_ID`'s own docstring): "Add" with
 * nothing selected defaults to the watermark placement, "Remove" always
 * clears `status_indicator` back to `None`, and the client-only Hide
 * toggle only appears while the watermark is the active placement.
 */

test.beforeEach(async ({ page }) => {
  // Each spec file gets a clean slate regardless of what a prior test in
  // this or another file left dirty (see playwright.config.ts's own
  // `workers: 1` comment for the full reasoning).
  await page.request.post("/api/discard");
  await page.goto("/");
  await expect(page.getByText("All changes saved")).toBeVisible();
  // The furniture pseudo-slide's own controls only render while it's
  // the selected "slide".
  await page.getByText("⚙ Furniture").click();
  await page.getByLabel(/Show furniture/).check();
});

test("Add with nothing selected defaults to the watermark placement", async ({ page }) => {
  const statusItem = page.locator(".element-list__item", { hasText: "Status" });
  await expect(statusItem.getByText(/will show "draft"/)).toBeVisible();

  await statusItem.getByRole("button", { name: "Add" }).click();

  await expect(statusItem.getByRole("button", { name: "Remove" })).toBeVisible();
  await expect(page.getByLabel("Status indicator")).toHaveValue("watermark");
  // The watermark is the one placement large/on-top enough to need a
  // client-only Hide toggle while editing other elements underneath it.
  await expect(statusItem.getByRole("button", { name: "Hide" })).toBeVisible();
});

test("selecting a corner from Deck Options materializes that corner, not the watermark", async ({
  page,
}) => {
  await page.getByLabel("Status indicator").selectOption({ label: "Corner: top-right" });

  const statusItem = page.locator(".element-list__item", { hasText: "Status" });
  await expect(statusItem.getByRole("button", { name: "Remove" })).toBeVisible();
  // A corner never shows a Hide toggle -- it's small and behind content,
  // nothing for a corner placement to obscure.
  await expect(statusItem.getByRole("button", { name: "Hide" })).not.toBeVisible();

  // Server truth: the corner's own style landed in design.yaml, not the
  // watermark's.
  await expect(statusItem.getByText(/configured \("draft"\)/)).toBeVisible();
});

test("Remove clears status_indicator back to None, matching the dropdown's own None option", async ({
  page,
}) => {
  const statusItem = page.locator(".element-list__item", { hasText: "Status" });
  await statusItem.getByRole("button", { name: "Add" }).click();
  await expect(page.getByLabel("Status indicator")).toHaveValue("watermark");

  await statusItem.getByRole("button", { name: "Remove" }).click();

  await expect(page.getByLabel("Status indicator")).toHaveValue("none");
  await expect(statusItem.getByRole("button", { name: "Add" })).toBeVisible();
});

test("Add is disabled with an explanation when there is no text to show yet", async ({ page }) => {
  await page.getByLabel("Deck status").fill("");
  await page.getByLabel("Deck status").blur();

  const statusItem = page.locator(".element-list__item", { hasText: "Status" });
  await expect(statusItem.getByText(/set Deck status above first/)).toBeVisible();
  await expect(statusItem.getByRole("button", { name: "Add" })).toBeDisabled();
});

test("there is no separate Show watermark checkbox in Deck Options", async ({ page }) => {
  // Regression guard for the redesign itself: the checkbox was removed
  // because it was functionally identical to this same Add button.
  await expect(page.getByLabel("Show watermark")).toHaveCount(0);
});
