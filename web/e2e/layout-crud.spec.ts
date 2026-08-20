import { test, expect } from "@playwright/test";

/** Real-browser coverage for layout add/remove (issue #30): the "+ Add
 * layout" form, the required "blank" layout's remove control being
 * disabled, and removing an in-use layout -- both the case where the
 * server accepts it (reassigning affected slides to "blank") and the
 * case where it's rejected because that reassignment would leave a
 * slide unbuildable (a real, discovered-not-designed edge case, see
 * CLAUDE.md's own "Layouts editor mode" note). */

test.beforeEach(async ({ page }) => {
  await page.request.post("/api/discard");
  await page.goto("/");
  await expect(page.getByText("All changes saved")).toBeVisible();
  await page.locator(".slide-list__mode-toggle").getByText("Layouts").click();
});

test("adds a layout with no zones, then it's selectable in the list", async ({ page }) => {
  const list = page.locator(".slide-list");
  await expect(list.getByText(/1\. title-content/)).toBeVisible();
  await expect(list.getByText(/2\. blank/)).toBeVisible();

  await list.getByText("+ Add layout").click();
  await list.getByLabel("New layout id").fill("e2e-new-layout");
  await list.getByRole("button", { name: "Add" }).click();

  await expect(list.getByText(/3\. e2e-new-layout/)).toBeVisible();
  await list.getByText(/3\. e2e-new-layout/).click();
  await expect(page.getByText("This layout has no zones defined yet.")).toBeVisible();
});

test("the blank layout's remove control is disabled", async ({ page }) => {
  const list = page.locator(".slide-list");
  const row = list.locator(".slide-list__row", { hasText: "blank" });
  await expect(row.getByTitle('"blank" is required and can\'t be removed')).toBeDisabled();
});

test("removing an unused layout requires a two-step confirm, no slides affected", async ({
  page,
}) => {
  const list = page.locator(".slide-list");
  await list.getByText("+ Add layout").click();
  await list.getByLabel("New layout id").fill("e2e-unused");
  await list.getByRole("button", { name: "Add" }).click();
  await expect(list.getByText(/3\. e2e-unused/)).toBeVisible();

  const row = list.locator(".slide-list__row", { hasText: "e2e-unused" });
  await row.getByTitle('Remove layout "e2e-unused"').click();
  await expect(row.getByText(/Remove .e2e-unused.\?/)).toBeVisible();
  // No slide uses it, so there's no "used by ..." warning.
  await expect(row.getByText(/Used by/)).not.toBeVisible();

  await row.getByRole("button", { name: "Confirm" }).click();
  await expect(list.getByText(/e2e-unused/)).toHaveCount(0);
});

test("removing an in-use layout that would break a slide is rejected, nothing committed", async ({
  page,
}) => {
  // minimal-deck's own `content-slide` uses "title-content" and only
  // overrides its `title` zone's `value` -- relying on the layout's own
  // zone for `type`/`box`, which `blank` (no zones) can't supply.
  const list = page.locator(".slide-list");
  const row = list.locator(".slide-list__row", { hasText: "title-content" });

  await row.getByTitle('Remove layout "title-content"').click();
  await expect(row.getByText(/Used by content-slide/)).toBeVisible();

  await row.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByText(/would leave content-slide unbuildable/)).toBeVisible();

  // The layout is still there -- nothing was committed.
  await expect(list.getByText(/1\. title-content/)).toBeVisible();
});
