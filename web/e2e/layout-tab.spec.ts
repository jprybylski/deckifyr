import { test, expect } from "@playwright/test";

/** Real-browser coverage for the Content/Layout tab (issue #23):
 * toggling into Layout view shows the selected slide's own layout's
 * zones (`title-content`, on `content-slide` in the minimal-deck
 * fixture) with a "shared layout" banner, and a zone's geometry can be
 * edited from there (via `ElementInspector`'s numeric fields, the
 * keyboard-driven counterpart to dragging -- more stable in a headless
 * browser than simulating a Konva drag gesture). */

test.beforeEach(async ({ page }) => {
  await page.request.post("/api/discard");
  await page.goto("/");
  await expect(page.getByText("All changes saved")).toBeVisible();
});

test("toggling to Layout view shows the shared-layout banner and its zones", async ({ page }) => {
  await page.getByText(/2\. content-slide/).click();
  await page.locator(".toolbar__view-toggle").getByText("Layout").click();

  await expect(page.getByText(/Editing shared layout .title-content./)).toBeVisible();

  // title-content's own "title" zone box, from layouts.yaml:
  // {x: 0.7in, y: 0.35in, width: 11.9in, height: 0.65in} -- at 96px/in.
  const canvas = page.locator(".slide-canvas__stage-wrap canvas").first();
  await canvas.click({ position: { x: (0.7 + 11.9 / 2) * 96, y: (0.35 + 0.65 / 2) * 96 } });

  await expect(page.getByText("title", { exact: true })).toBeVisible();
  await expect(page.getByText(/is a zone of layout .title-content./)).toBeVisible();
});

test("editing a zone's geometry in Layout view persists (shared across slides using it)", async ({
  page,
}) => {
  await page.getByText(/2\. content-slide/).click();
  await page.locator(".toolbar__view-toggle").getByText("Layout").click();

  const canvas = page.locator(".slide-canvas__stage-wrap canvas").first();
  await canvas.click({ position: { x: (0.7 + 11.9 / 2) * 96, y: (0.35 + 0.65 / 2) * 96 } });
  await expect(page.getByText(/is a zone of layout .title-content./)).toBeVisible();

  const xField = page.getByLabel("X (in)");
  await expect(xField).toHaveValue("0.7000");
  await xField.fill("1.5");
  await page.getByRole("button", { name: "Apply" }).click();

  await expect(xField).toHaveValue("1.5000");

  // Re-fetching the layout's zones directly confirms this really
  // reached layouts.yaml's working copy, not just local input state.
  const zones = await page.request.get("/api/layouts/title-content");
  const body = await zones.json();
  const title = body.elements.find((el: { id: string }) => el.id === "title");
  expect(title.box.x).toBe("1.5in");
});

test("the Layout toggle is disabled on the furniture pseudo-slide", async ({ page }) => {
  await page.getByText("⚙ Furniture").click();
  await expect(page.locator(".toolbar__view-toggle").getByText("Layout")).toBeDisabled();
});
