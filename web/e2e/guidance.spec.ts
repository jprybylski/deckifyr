import { test, expect, type Page } from "@playwright/test";

/** Issue #105: a host page on the editor's own origin frames the editor
 * and asks it to highlight controls through the guidance hook
 * (`src/guidance.ts`). The host page is served by a Playwright route on
 * the same origin, so nothing is added to the real static bundle. */

const HOST = `<!doctype html><html><body>
<iframe id="ed" src="/" style="width:1200px;height:800px"></iframe>
<script>
  window.replies = [];
  window.addEventListener("message", (e) => {
    if (e.source === document.getElementById("ed").contentWindow) window.replies.push(e.data);
  });
  window.ask = (msg) => document.getElementById("ed").contentWindow.postMessage(msg, location.origin);
</script></body></html>`;

test.beforeEach(async ({ page }) => {
  await page.request.post("/api/discard");
  await page.route("**/__guidance-host.html", (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: HOST }),
  );
  await page.goto("/__guidance-host.html");
  await expect(page.frameLocator("#ed").getByText("All changes saved")).toBeVisible();
});

async function ask(page: Page, op: string, id: string | undefined, seq: number) {
  await page.evaluate((m) => (window as any).ask(m), { type: "guidance", v: 1, op, id, seq });
}

async function reply(page: Page, seq: number) {
  await expect
    .poll(() => page.evaluate((s) => (window as any).replies.find((r: any) => r.seq === s), seq))
    .toBeTruthy();
  return page.evaluate((s) => (window as any).replies.find((r: any) => r.seq === s), seq);
}

test("highlights the Build tab, then reports the Build button absent until that tab is open", async ({ page }) => {
  const frame = page.frameLocator("#ed");
  await ask(page, "highlight", "deckifyr.nav.build", 1);
  expect((await reply(page, 1)).state).toBe("shown");
  await expect(frame.locator('[data-target="deckifyr.nav.build"]')).toHaveClass(/deckifyr-guidance-target/);

  await ask(page, "highlight", "deckifyr.build.run", 2);
  expect((await reply(page, 2)).state).toBe("absent");
  await expect(frame.locator(".deckifyr-guidance-target")).toHaveCount(0);

  await frame.locator('[data-target="deckifyr.nav.build"]').click();
  await ask(page, "highlight", "deckifyr.build.run", 3);
  expect((await reply(page, 3)).state).toBe("shown");
  await expect(frame.locator(".build-panel .deckifyr-guidance-target")).toHaveCount(1);

  await ask(page, "clear", undefined, 4);
  await expect(frame.locator(".deckifyr-guidance-target")).toHaveCount(0);
});

test("a highlight does not switch tabs or move focus", async ({ page }) => {
  const frame = page.frameLocator("#ed");
  await ask(page, "highlight", "deckifyr.session.save", 1);
  expect((await reply(page, 1)).state).toBe("shown");
  await expect(frame.locator(".build-panel")).toHaveCount(0);
  const focused = await page.frames()[1].evaluate(() => document.activeElement?.tagName);
  expect(focused).toBe("BODY");
});

test("the editor ignores a message from a window that is not its parent", async ({ page }) => {
  const frame = page.frameLocator("#ed");
  // The editor posting to itself: right origin, wrong source.
  await page.frames()[1].evaluate(() =>
    window.postMessage(
      { type: "guidance", v: 1, op: "highlight", id: "deckifyr.session.save", seq: 9 },
      location.origin,
    ),
  );
  await page.waitForTimeout(300);
  await expect(frame.locator(".deckifyr-guidance-target")).toHaveCount(0);
  expect(await page.evaluate(() => (window as any).replies.length)).toBe(0);
});
