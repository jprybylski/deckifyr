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
  // Two independent warnings now legitimately coexist (issue #32
  // follow-up): one next to the "Render slide previews" checkbox, one
  // in the standalone Preview section below.
  await expect(panel.getByText(/isn.t installed/)).toHaveCount(2);
  for (const link of await panel.getByRole("link", { name: /Install LibreOffice/ }).all()) {
    await expect(link).toHaveAttribute("href", "https://www.libreoffice.org/download/download/");
  }
  await expect(
    panel.getByRole("checkbox", { name: "Render slide previews (PNG + PDF) with this build" })
  ).toBeDisabled();
  await expect(panel.getByRole("button", { name: "Preview" })).toBeDisabled();
});

test("Preview shows a progress bar, then rendered images and a collapsed PDF disclosure (issue #32)", async ({
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
        result: { previews: ["a.png", "b.png"], preview_pdf: "a.pdf" },
        error: null,
      },
    })
  );
  await page.route("**/api/jobs/e2e-preview-job/artifacts", (route) =>
    route.fulfill({ json: { artifacts: ["pptx", "preview-0", "preview-1", "pdf"] } })
  );
  await page.reload();
  await page.getByRole("button", { name: "Build" }).click();

  const panel = page.locator(".build-panel");
  await panel.getByRole("button", { name: "Preview" }).click();

  const firstImage = panel.getByRole("img", { name: "preview-0" });
  const secondImage = panel.getByRole("img", { name: "preview-1" });
  await expect(firstImage).toBeVisible();

  // The PDF is minimized by default -- not shown, and not requested
  // (`page.route` above would still resolve a fetch either way, but the
  // component test suite already covers "never mounts the iframe until
  // asked"; this just confirms the real UI starts collapsed).
  await expect(panel.getByTitle("Preview PDF")).not.toBeVisible();
  await panel.getByText("Show PDF preview").click();
  await expect(panel.getByTitle("Preview PDF")).toHaveAttribute(
    "src",
    "/api/jobs/e2e-preview-job/artifacts/pdf"
  );

  // PNG thumbnails expand on click, one at a time.
  await expect(firstImage).not.toHaveClass(/preview-gallery__image--expanded/);
  await firstImage.click();
  await expect(firstImage).toHaveClass(/preview-gallery__image--expanded/);
  await expect(secondImage).not.toHaveClass(/preview-gallery__image--expanded/);

  await secondImage.click();
  await expect(firstImage).not.toHaveClass(/preview-gallery__image--expanded/);
  await expect(secondImage).toHaveClass(/preview-gallery__image--expanded/);

  await secondImage.click();
  await expect(secondImage).not.toHaveClass(/preview-gallery__image--expanded/);
});

test("the output-path browser navigates the real project tree and picks a path (issue #32)", async ({
  page,
}) => {
  const panel = page.locator(".build-panel");

  // Run a real build first so `build/` actually exists on disk -- makes
  // this test's own listing assertions deterministic regardless of
  // whatever order the other spec files in this shared-server run
  // happen to execute in (see `playwright.config.ts`'s own "All spec
  // files share one deckifyr serve process" note).
  await panel.getByRole("button", { name: "Build" }).click();
  await expect(panel.getByText("Status: succeeded")).toBeVisible({ timeout: 30_000 });

  await panel.getByRole("button", { name: "Browse…" }).click();

  // Opens at the current value's own directory ("build/", the fixture's
  // own default `build.output`), not the project root.
  const browser = panel.locator(".output-path-browser");
  await expect(browser.getByText("minimal-deck.pptx")).toBeVisible();

  // Navigate up to the real project root and confirm a real, live
  // listing of it (not a canned fixture).
  await browser.getByRole("button", { name: ".. (up)" }).click();
  await expect(browser.getByText("presentation.yaml")).toBeVisible();
  await expect(browser.getByText("design.yaml")).toBeVisible();
  await browser.getByText("📁 build").click();
  await expect(browser.getByText("minimal-deck.pptx")).toBeVisible();

  await browser.getByLabel("Filename").fill("picked-by-e2e.pptx");
  await browser.getByRole("button", { name: "Use this path" }).click();

  await expect(panel.getByLabel("Output path")).toHaveValue("build/picked-by-e2e.pptx");
  await expect(page.getByText("Unsaved changes")).toBeVisible();

  const doc = await (await page.request.get("/api/config/presentation")).json();
  expect(doc.build.output).toBe("build/picked-by-e2e.pptx");
});
