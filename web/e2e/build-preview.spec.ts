import { test, expect } from "@playwright/test";

/** Real-browser coverage for the Build tab's issue #27 additions:
 * editing/saving `build.output`, and the Preview flow (availability
 * check, progress bar, preview images, embedded PDF viewer, missing-
 * dependency message). The Preview flow itself is exercised against
 * `page.route`-mocked `/api/preview*`/`/api/jobs/*` responses rather
 * than a real LibreOffice render -- this e2e tier shouldn't assume
 * `soffice` is on the machine running it, mirroring this repo's
 * existing "skip/mock cleanly without the real external binary"
 * posture for anything Playwright-tier (`playwright.config.ts`'s own
 * header comment); a real render is covered by the soffice-gated
 * `tests/python` integration tests instead. */

test.beforeEach(async ({ page }) => {
  await page.request.post("/api/discard");
  await page.goto("/");
  await expect(page.getByText("All changes saved")).toBeVisible();
  await page.getByRole("button", { name: "Build" }).click();
});

test("editing the build output path syncs to the working copy of presentation.yaml", async ({
  page,
}) => {
  // Deliberately does not Save (left for the next test's `beforeEach`
  // discard to revert, per this file's own convention) -- `GET
  // /api/config/presentation` already reads the in-memory working copy,
  // not disk, so that's enough to prove the edit reached the server.
  const panel = page.locator(".build-panel");
  const input = panel.getByLabel("Output path");
  await expect(input).toHaveValue("build/minimal-deck.pptx");

  await input.fill("build/renamed-by-e2e.pptx");
  await input.blur();
  await expect(page.getByText("Unsaved changes")).toBeVisible();

  const doc = await (await page.request.get("/api/config/presentation")).json();
  expect(doc.build.output).toBe("build/renamed-by-e2e.pptx");
});

test("shows an install link and disables Preview when LibreOffice isn't available", async ({
  page,
}) => {
  await page.route("**/api/preview/availability", (route) =>
    route.fulfill({
      json: {
        available: false,
        binary: "soffice",
        display_name: "LibreOffice",
        install_url: "https://www.libreoffice.org/download/download/",
      },
    })
  );
  await page.reload();
  await page.getByRole("button", { name: "Build" }).click();

  const panel = page.locator(".build-panel");
  await expect(panel.getByText(/isn.t installed/)).toBeVisible();
  await expect(panel.getByRole("link", { name: /Install LibreOffice/ })).toHaveAttribute(
    "href",
    "https://www.libreoffice.org/download/download/"
  );
  await expect(panel.getByRole("button", { name: "Preview" })).toBeDisabled();
});

test("Preview shows a progress bar, then rendered images and an embedded PDF viewer", async ({
  page,
}) => {
  await page.route("**/api/preview/availability", (route) =>
    route.fulfill({
      json: { available: true, binary: "soffice", display_name: "LibreOffice", install_url: null },
    })
  );
  await page.route("**/api/preview", (route) =>
    route.fulfill({ json: { job_id: "e2e-preview-job" } })
  );
  await page.route("**/api/jobs/e2e-preview-job", (route) =>
    route.fulfill({
      json: {
        id: "e2e-preview-job",
        status: "succeeded",
        result: { previews: ["a.png"], preview_pdf: "a.pdf" },
        error: null,
      },
    })
  );
  await page.route("**/api/jobs/e2e-preview-job/artifacts", (route) =>
    route.fulfill({ json: { artifacts: ["pptx", "preview-0", "pdf"] } })
  );
  await page.reload();
  await page.getByRole("button", { name: "Build" }).click();

  const panel = page.locator(".build-panel");
  await panel.getByRole("button", { name: "Preview" }).click();

  await expect(panel.getByRole("img", { name: "preview-0" })).toBeVisible();
  await expect(panel.getByTitle("Preview PDF")).toHaveAttribute(
    "src",
    "/api/jobs/e2e-preview-job/artifacts/pdf"
  );
});
