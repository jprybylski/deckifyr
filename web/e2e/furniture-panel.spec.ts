import { test, expect } from "@playwright/test";

/** Real-browser coverage for the furniture pseudo-slide's Branding/Page
 * number Add/Remove and the canvas's "Show furniture" visibility toggle
 * (issue #21). Background is deliberately not covered here -- it has no
 * Add/Remove of its own, only a Config-tab reminder. */

test.beforeEach(async ({ page }) => {
  // Each spec file gets a clean slate regardless of what a prior test in
  // this or another file left dirty (see playwright.config.ts's own
  // `workers: 1` comment for the full reasoning).
  await page.request.post("/api/discard");
  await page.goto("/");
  await expect(page.getByText("All changes saved")).toBeVisible();
});

test("Show furniture toggles whether the furniture overlay is clickable on the real slide canvas", async ({
  page,
}) => {
  // Furniture placeholder labels are drawn with Konva's own `<Text>`
  // onto the canvas bitmap, not real DOM -- `getByText` can never find
  // them regardless of visibility, so this proves the toggle's effect
  // indirectly instead: click where the branding placeholder's default
  // box lands and check the properties panel picks it up, the same
  // canvas-click technique `discard.spec.ts` already relies on.
  //
  // Branding isn't configured in the minimal-deck fixture by default --
  // it must actually be added before it has anything to toggle the
  // visibility of. Default box (`_default_furniture_value` in app.py,
  // 13.333x7.5in slide): x=0.25in, y=6.95in, width=3in, height=0.35in.
  await page.getByText("⚙ Furniture").click();
  await page.getByLabel(/Show furniture/).check();
  await page
    .locator(".furniture-controls__item", { hasText: "Branding" })
    .getByRole("button", { name: "Add" })
    .click();

  await page.getByText("1. title").click();
  const canvas = page.locator(".slide-canvas__stage-wrap canvas").first();
  const brandingCenter = { x: (0.25 + 3 / 2) * 96, y: (6.95 + 0.35 / 2) * 96 };
  // minimal-deck's own title-slide element (box: x=0.9in, y=2.1in,
  // width=11.5in, height=1.1in) -- used below purely to move selection
  // *away* from branding between the two assertions; `showFurniture` is
  // a pure view filter that never touches selection state on its own
  // (`SlideCanvas.tsx`'s own comment), so re-clicking the same branding
  // position after hiding it must be checked against a *changed*
  // selection, not an assumed "nothing selected" end state.
  const titleCenter = { x: (0.9 + 11.5 / 2) * 96, y: (2.1 + 1.1 / 2) * 96 };

  await canvas.click({ position: brandingCenter });
  await expect(page.getByText("__furniture_branding")).toBeVisible();

  await canvas.click({ position: titleCenter });
  await expect(page.getByText("deck-title")).toBeVisible();

  await page.getByLabel(/Show furniture/).uncheck();
  await canvas.click({ position: brandingCenter });
  // Branding is filtered out of what's paintable/clickable now -- the
  // click lands on nothing furniture-related, so selection stays on
  // deck-title rather than picking up branding again.
  await expect(page.getByText("deck-title")).toBeVisible();
  await expect(page.getByText("__furniture_branding")).not.toBeVisible();
});

test("Branding: Add creates a default style, Remove deletes it", async ({ page }) => {
  await page.getByText("⚙ Furniture").click();
  await page.getByLabel(/Show furniture/).check();

  const brandingItem = page.locator(".furniture-controls__item", { hasText: "Branding" });
  await brandingItem.getByRole("button", { name: "Add" }).click();
  await expect(brandingItem.getByRole("button", { name: "Remove" })).toBeVisible();

  await brandingItem.getByRole("button", { name: "Remove" }).click();
  await expect(brandingItem.getByRole("button", { name: "Add" })).toBeVisible();
});

test("Page number: Add creates a default style, Remove deletes it", async ({ page }) => {
  await page.getByText("⚙ Furniture").click();
  await page.getByLabel(/Show furniture/).check();

  const pageNumberItem = page.locator(".furniture-controls__item", { hasText: "Page number" });
  await pageNumberItem.getByRole("button", { name: "Add" }).click();
  await expect(pageNumberItem.getByRole("button", { name: "Remove" })).toBeVisible();

  await pageNumberItem.getByRole("button", { name: "Remove" }).click();
  await expect(pageNumberItem.getByRole("button", { name: "Add" })).toBeVisible();
});

test("selecting the Furniture pseudo-slide shows its own controls, an ordinary slide does not", async ({
  page,
}) => {
  await expect(page.locator(".furniture-controls")).not.toBeVisible();

  await page.getByText("⚙ Furniture").click();
  await expect(page.locator(".furniture-controls")).toBeVisible();

  await page.getByText("2. content-slide").click();
  await expect(page.locator(".furniture-controls")).not.toBeVisible();
});
