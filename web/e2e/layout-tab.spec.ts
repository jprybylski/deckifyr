import { test, expect } from "@playwright/test";

/** Real-browser coverage for the Layouts editor mode (issue #30):
 * toggling `SlideList`'s persistent "Slides / Layouts" mode swaps the
 * entire slide list to `layouts.yaml`'s own layouts, shows a "shared
 * layout" banner while one is selected, and a zone's geometry can be
 * edited from there (via `ElementInspector`'s numeric fields, the
 * keyboard-driven counterpart to dragging -- more stable in a headless
 * browser than simulating a Konva drag gesture). This supersedes issue
 * #23's per-slide Content/Layout tab, which this same fixture used to
 * exercise via `.toolbar__view-toggle` (removed). */

test.beforeEach(async ({ page }) => {
  await page.request.post("/api/discard");
  await page.goto("/");
  await expect(page.getByText("All changes saved")).toBeVisible();
});

test("toggling to Layouts shows the shared-layout banner and its zones", async ({ page }) => {
  await page.locator(".slide-list__mode-toggle").getByText("Layouts").click();
  await page.getByText(/1\. title-content/).click();

  await expect(page.getByText(/Editing shared layout .title-content./)).toBeVisible();

  // title-content's own "title" zone box, from layouts.yaml:
  // {x: 0.7in, y: 0.35in, width: 11.9in, height: 0.65in} -- at 96px/in.
  const canvas = page.locator(".slide-canvas__stage-wrap canvas").first();
  await canvas.click({ position: { x: (0.7 + 11.9 / 2) * 96, y: (0.35 + 0.65 / 2) * 96 } });

  await expect(page.getByText("title", { exact: true })).toBeVisible();
  await expect(page.getByText(/is a zone of layout .title-content./)).toBeVisible();
});

test("editing a zone's geometry in Layouts mode persists (shared across slides using it)", async ({
  page,
}) => {
  await page.locator(".slide-list__mode-toggle").getByText("Layouts").click();
  await page.getByText(/1\. title-content/).click();

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

test("the mode toggle persists across selecting the furniture pseudo-slide", async ({ page }) => {
  // Issue #30's own wording: the toggle "remains persistent across the
  // slides being edited" -- unlike the superseded per-slide tab, nothing
  // about selecting Furniture resets or disables it.
  await page.locator(".slide-list__mode-toggle").getByText("Layouts").click();
  await page.getByText("⚙ Furniture").click();

  await expect(page.locator(".slide-list__mode-toggle").getByText("Layouts")).toHaveClass(
    /active/
  );

  await page.locator(".slide-list__mode-toggle").getByText("Slides").click();
  await expect(page.getByText(/2\. content-slide/)).toBeVisible();
});
