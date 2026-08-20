import { test, expect } from "@playwright/test";

/** Real-browser coverage for element add/remove on an ordinary slide
 * (issue #31): the "+ Add element" form and each row's own Remove
 * button, against the real `deckifyr serve` fixture. Furniture's own
 * Add/Remove is covered separately by `furniture-panel.spec.ts`; layout
 * zone add/remove follows the same code path, exercised once by
 * `layout-tab.spec.ts`'s own sibling coverage. */

test.beforeEach(async ({ page }) => {
  await page.request.post("/api/discard");
  await page.goto("/");
  await expect(page.getByText("All changes saved")).toBeVisible();
  await page.getByText(/1\. title/).click();
});

test("adds a text element with a default box, then it's selectable and removable", async ({
  page,
}) => {
  const sidebar = page.locator(".element-list");
  await expect(sidebar.getByText("markdown: deck-title")).toBeVisible();

  await sidebar.getByText("+ Add element").click();
  await sidebar.getByLabel("New element id").fill("e2e-new-el");
  await sidebar.getByLabel("Value").fill("hello from e2e");
  await sidebar.getByRole("button", { name: "Add" }).click();

  const row = sidebar.locator(".element-list__item", { hasText: "text: e2e-new-el" });
  await expect(row).toBeVisible();

  // Selecting the row expands ElementInspector's own numeric form.
  await row.getByText("text: e2e-new-el").click();
  await expect(page.getByLabel("X (in)")).toBeVisible();

  await row.getByRole("button", { name: "Remove" }).click();
  await expect(sidebar.locator(".element-list__item", { hasText: "e2e-new-el" })).toHaveCount(0);
});

test("Add is disabled when the id duplicates an existing element on this slide", async ({
  page,
}) => {
  const sidebar = page.locator(".element-list");
  await sidebar.getByText("+ Add element").click();
  await sidebar.getByLabel("New element id").fill("deck-title");

  await expect(sidebar.getByRole("button", { name: "Add" })).toBeDisabled();
  await expect(sidebar.getByText(/an element with this id already exists/)).toBeVisible();
});
