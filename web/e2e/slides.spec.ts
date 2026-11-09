import { test, expect } from "@playwright/test";

/** Real-browser coverage for add/remove/duplicate slide (issues #23,
 * #31): the "+ Add slide" form (id + layout picker), each row's subtle
 * corner remove (a two-step confirm) and duplicate icon buttons, against
 * the real `deckifyr serve` fixture. */

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
  // "blank" keeps this test about add/select only; filling a layout with a
  // required zone (title-content) has its own tests below (issue #101).
  await list.locator(".slide-list__add-form").getByLabel("Layout").selectOption("blank");
  await list.getByRole("button", { name: "Add" }).click();

  await expect(list.getByText(/3\. e2e-new-slide/)).toBeVisible();
  await list.getByText(/3\. e2e-new-slide/).click();
  // Selecting it should be reflected in the active slide -- "blank" is a
  // real (if empty) named layout, so the sidebar's element list shows
  // for it with nothing to add-remove yet (an ordinary, if empty, slide).
  await expect(page.getByRole("heading", { name: "Elements" })).toBeVisible();
});

test("adding with no layout picked creates a freeform slide", async ({ page }) => {
  const list = page.locator(".slide-list");
  await list.getByText("+ Add slide").click();
  await list.getByLabel("New slide id").fill("e2e-freeform-slide");
  // Leave "Layout" at its default "Freeform (no layout)" option.
  await list.getByRole("button", { name: "Add" }).click();

  await expect(list.getByText(/3\. e2e-freeform-slide/)).toBeVisible();
  await list.getByText(/3\. e2e-freeform-slide/).click();
  await expect(page.getByRole("heading", { name: "Elements" })).toBeVisible();
});

test("removing a slide requires a two-step confirm", async ({ page }) => {
  const list = page.locator(".slide-list");
  const row = list.locator(".slide-list__row", { hasText: "content-slide" });

  // The corner "×" button is a subtle icon, not a "Remove" text button
  // (issue #31 follow-up) -- targeted by its own `title` tooltip, the
  // same way a user would discover what it does by hovering.
  await row.getByTitle('Remove slide "content-slide"').click();
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
  await row.getByTitle('Remove slide "content-slide"').click();
  await row.getByRole("button", { name: "Confirm" }).click();
  await expect(row).toHaveCount(0);
  await expect(list.getByText(/1\. title/)).toBeVisible();
});

test("duplicating a slide inserts a '-copy' immediately after it, no confirm needed", async ({
  page,
}) => {
  const list = page.locator(".slide-list");
  const row = list.locator(".slide-list__row", { hasText: "title" }).first();

  await row.getByTitle('Duplicate slide "title"').click();

  await expect(list.getByText(/2\. title-copy/)).toBeVisible();
  await expect(list.getByText(/3\. content-slide/)).toBeVisible();
});

test("a title-content slide can be filled in entirely in the app (issue #101)", async ({
  page,
}) => {
  const list = page.locator(".slide-list");
  await list.getByText("+ Add slide").click();
  await list.getByLabel("New slide id").fill("e2e-filled");
  await list.locator(".slide-list__add-form").getByLabel("Layout").selectOption("title-content");
  await list.getByRole("button", { name: "Add" }).click();

  // Lands on the new slide, flagged as needing its required title.
  const row = list.locator(".slide-list__row", { hasText: "e2e-filled" });
  await expect(row.getByLabel("Needs content: title")).toBeVisible();
  const elements = page.locator(".element-list");
  await expect(elements.getByText("title (required) -- empty")).toBeVisible();
  await expect(elements.getByText("content -- empty")).toBeVisible();

  // Title: a text zone, filled from the inspector's Content field.
  await elements.getByText("title (required) -- empty").click();
  await elements.getByLabel("Content").fill("A brand new title");
  await elements.getByRole("button", { name: "Set content" }).click();
  await expect(elements.getByText("text: title")).toBeVisible();
  await expect(row.getByLabel("Needs content: title")).toHaveCount(0);

  // Content: a slot, which needs a type chosen -- Fill... keeps the layout's box.
  await elements.getByRole("button", { name: "Fill…" }).click();
  await elements.getByLabel("Value").fill("Some body text");
  await elements.getByRole("button", { name: "Add", exact: true }).click();
  await expect(elements.getByText("markdown: content")).toBeVisible();
  await expect(row.getByText("(2)*")).toBeVisible();

  // Nothing left to fill, and the whole deck builds-clean plan-wise.
  const plan = await (await page.request.get("/api/plan")).json();
  const slide = plan.slides.find((s: { id: string }) => s.id === "e2e-filled");
  expect(slide.error).toBeUndefined();
  expect(slide.elements.some((e: { unfilled?: boolean }) => e.unfilled)).toBe(false);
});

test("an incomplete slide never hides the others after a reload, and can be removed (issue #101)", async ({
  page,
}) => {
  const list = page.locator(".slide-list");
  await list.getByText("+ Add slide").click();
  await list.getByLabel("New slide id").fill("e2e-incomplete");
  await list.locator(".slide-list__add-form").getByLabel("Layout").selectOption("title-content");
  await list.getByRole("button", { name: "Add" }).click();
  await expect(list.getByText(/3\. e2e-incomplete/)).toBeVisible();

  // The working copy (and its incomplete slide) survives a reload -- that
  // is the case that used to blank the whole editor.
  await page.reload();

  await expect(list.getByText(/1\. title/)).toBeVisible();
  await expect(list.getByText(/2\. content-slide/)).toBeVisible();
  const row = list.locator(".slide-list__row", { hasText: "e2e-incomplete" });
  await expect(row.getByLabel("Needs content: title")).toBeVisible();
  await expect(page.locator(".slide-list__error")).toHaveCount(0);

  // Other slides are still editable ...
  await list.getByText(/2\. content-slide/).click();
  await expect(page.locator(".slide-canvas canvas").first()).toBeVisible();

  // ... and the incomplete one can simply be removed.
  await row.getByTitle('Remove slide "e2e-incomplete"').click();
  await row.getByRole("button", { name: "Confirm" }).click();
  await expect(row).toHaveCount(0);
  await expect(list.getByText(/2\. content-slide/)).toBeVisible();
});
