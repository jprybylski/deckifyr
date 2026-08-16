import { test, expect } from "@playwright/test";

/** Real-browser coverage for add/remove slide (issue #23): the "+ Add
 * slide" form (id + layout picker) and each row's two-step Remove
 * confirm, against the real `deckifyr serve` fixture. */

test.beforeEach(async ({ page }) => {
  // Each test gets a clean slate regardless of what a prior test in this
  // or another file left dirty (see playwright.config.ts's own
  // `workers: 1` comment for the full reasoning).
  await page.request.post("/api/discard");
  await page.goto("/");
  await expect(page.getByText("All changes saved")).toBeVisible();
});

test("adds a slide with a picked layout, then it's selectable in the list", async ({ page }) => {
  const list = page.locator(".slide-list");
  await expect(list.getByText(/1\. title/)).toBeVisible();
  await expect(list.getByText(/2\. content-slide/)).toBeVisible();

  await list.getByText("+ Add slide").click();
  await list.getByLabel("New slide id").fill("e2e-new-slide");
  // "blank" (a real, named, empty layout, spec section 7.5) rather than
  // "title-content" -- that layout's own "title" zone is `required:
  // true`, which a freshly-added slide with no content overrides of its
  // own can never satisfy, so `GET /api/plan`'s real-slide resolution
  // would (correctly) reject the whole plan until content is added. Not
  // a bug this feature needs to route around -- see the original
  // issue's own "quick layout (or empty except for furniture)" framing,
  // which already expects Add's common case to be exactly this kind of
  // still-needs-content-filled-in starting point.
  await list.getByLabel("Layout").selectOption("blank");
  await list.getByRole("button", { name: "Add" }).click();

  await expect(list.getByText(/3\. e2e-new-slide/)).toBeVisible();
  await list.getByText(/3\. e2e-new-slide/).click();
  // Selecting it should be reflected in the active slide -- "blank" is a
  // real (if empty) named layout, so the Layout toggle is enabled (even
  // though its own canvas view will just say "no zones defined yet").
  await expect(page.locator(".toolbar__view-toggle").getByText("Layout")).toBeEnabled();
});

test("adding with no layout picked creates a freeform slide", async ({ page }) => {
  const list = page.locator(".slide-list");
  await list.getByText("+ Add slide").click();
  await list.getByLabel("New slide id").fill("e2e-freeform-slide");
  // Leave "Layout" at its default "Freeform (no layout)" option.
  await list.getByRole("button", { name: "Add" }).click();

  await expect(list.getByText(/3\. e2e-freeform-slide/)).toBeVisible();
  await list.getByText(/3\. e2e-freeform-slide/).click();
  // A freeform slide has no layout to edit -- the toggle stays disabled.
  await expect(page.locator(".toolbar__view-toggle").getByText("Layout")).toBeDisabled();
});

test("removing a slide requires a two-step confirm", async ({ page }) => {
  const list = page.locator(".slide-list");
  const row = list.locator(".slide-list__row", { hasText: "content-slide" });

  // The button's visible text (its accessible name) is just "Remove" --
  // `title="Remove slide \"content-slide\""` is a tooltip, not the name,
  // since accname computation prefers text content when both are present.
  await row.getByRole("button", { name: "Remove", exact: true }).click();
  await expect(row.getByText(/Remove .content-slide.\?/)).toBeVisible();

  // Cancel keeps it.
  await row.getByRole("button", { name: "Cancel" }).click();
  await expect(list.getByText(/2\. content-slide/)).toBeVisible();

  // Confirm actually removes it. Waits on `row` itself disappearing
  // (not a text locator) -- a locator that briefly matches more than
  // one element mid-removal (the old row plus its own confirm text)
  // makes `toBeVisible`/`not.toBeVisible` fail immediately on the
  // strict-mode violation rather than retry past it, confirmed the hard
  // way while writing this test.
  await row.getByRole("button", { name: "Remove", exact: true }).click();
  await row.getByRole("button", { name: "Confirm" }).click();
  await expect(row).toHaveCount(0);
  await expect(list.getByText(/1\. title/)).toBeVisible();
});
