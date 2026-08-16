import { test, expect } from "@playwright/test";

/** Real-browser coverage for the Config tab: switching documents, the
 * Form/Raw view toggle, and a real edit round-tripping through each
 * view (`ConfigEditor.tsx`, issue #22). */

test.beforeEach(async ({ page }) => {
  // Each spec file gets a clean slate regardless of what a prior test in
  // this or another file left dirty (see playwright.config.ts's own
  // `workers: 1` comment for the full reasoning).
  await page.request.post("/api/discard");
  await page.goto("/");
  await expect(page.getByText("All changes saved")).toBeVisible();
  await page.getByRole("button", { name: "Config" }).click();
});

test("defaults to the Form view (on design.yaml) and can switch documents", async ({ page }) => {
  await expect(page.getByRole("button", { name: "Form" })).toHaveClass(
    /config-editor__view-btn--active/
  );
  // design.yaml is the default document -- its own top-level fields
  // should be visible as form inputs.
  await expect(page.getByText("colors").first()).toBeVisible();

  await page.getByLabel("Document").selectOption("presentation");
  await expect(page.getByText("deckifyr").first()).toBeVisible();
});

test("Raw view shows valid JSON that live-validates on edit", async ({ page }) => {
  await page.getByRole("button", { name: "Raw" }).click();
  const textarea = page.locator(".config-editor__textarea--overlay");
  await expect(textarea).toBeVisible();
  const text = await textarea.inputValue();
  expect(() => JSON.parse(text)).not.toThrow();

  await textarea.fill("{ not valid json");
  // Switching back to Form while raw text doesn't parse must be
  // blocked -- the form must never be handed a value that doesn't match
  // what's on screen.
  await page.getByRole("button", { name: "Form" }).click();
  await expect(page.getByRole("button", { name: "Raw" })).toHaveClass(
    /config-editor__view-btn--active/
  );
});

test("editing Deck status via Raw and Apply round-trips through the API", async ({ page }) => {
  await page.getByLabel("Document").selectOption("presentation");
  await page.getByRole("button", { name: "Raw" }).click();
  const textarea = page.locator(".config-editor__textarea--overlay");
  const original = JSON.parse(await textarea.inputValue());
  const edited = { ...original, metadata: { ...original.metadata, status: "e2e-test-status" } };
  await textarea.fill(JSON.stringify(edited, null, 2));

  await page.getByRole("button", { name: "Apply" }).click();
  await expect(
    page.getByText("Applied to this session -- use the header's Save to write it to disk.")
  ).toBeVisible();

  // Confirms the edit actually reached the server's working copy, not
  // just the local textarea.
  await page.getByRole("button", { name: "Editor" }).click();
  await expect(page.getByLabel("Deck status")).toHaveValue("e2e-test-status");
});
