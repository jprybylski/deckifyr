import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import FurnitureControls from "./FurnitureControls";
import { AppProvider } from "../state/AppContext";
import type { UsePlanResult } from "../state/usePlan";
import type { ResolvedElement, ResolvedSlide } from "../types";

function renderControls(plan: UsePlanResult) {
  return render(
    <AppProvider>
      <FurnitureControls plan={plan} />
    </AppProvider>
  );
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function furnitureElement(id: string): ResolvedElement {
  return {
    id,
    type: "text",
    value: null,
    source: null,
    box: { x: "0in", y: "0in", width: "1in", height: "1in" },
    rotation: 0,
    z_index: -10,
    order: 0,
    style: null,
    fit: "shrink",
    overflow: "clip",
    render_mode: "native",
    alt_text: null,
    required: false,
    footer_placement: null,
    shape_kind: null,
    shape_style: null,
    table_style: null,
    center: false,
    align: null,
    children: [],
  };
}

function makePlan(furnitureSlide: ResolvedSlide | null, refetch: () => Promise<void>): UsePlanResult {
  return {
    slides: [],
    furnitureSlide,
    slideSize: { widthIn: 13.333, heightIn: 7.5 },
    loading: false,
    error: null,
    refetch,
    applyElementPatch: vi.fn(),
    undo: vi.fn(),
    redo: vi.fn(),
    canUndo: false,
    canRedo: false,
  };
}

/** Builds a fetch mock covering the two GETs `FurnitureControls` always
 * makes (`presentation`/`design`) plus any extra routes a test needs. */
function stubFetch(
  presentation: Record<string, unknown>,
  design: Record<string, unknown> = {},
  extra: (url: string, method: string, init?: RequestInit) => Promise<Response> | undefined = () =>
    undefined,
) {
  return vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url === "/api/config/presentation" && method === "GET") {
      return Promise.resolve(jsonResponse(200, presentation));
    }
    if (url === "/api/config/design" && method === "GET") {
      return Promise.resolve(jsonResponse(200, design));
    }
    const handled = extra(url, method, init);
    if (handled) return handled;
    return Promise.reject(new Error(`unexpected fetch: ${url} ${method}`));
  });
}

function itemFor(labelText: string): HTMLElement {
  return screen.getByText(labelText).closest(".furniture-controls__item") as HTMLElement;
}

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

describe("FurnitureControls", () => {
  it("offers Add for an unconfigured branding item and calls the add route", async () => {
    const fetchMock = stubFetch({ status_indicator: "none" }, {}, (url, method) => {
      if (url === "/api/furniture/elements/__furniture_branding" && method === "POST") {
        return Promise.resolve(jsonResponse(200, { element: "__furniture_branding" }));
      }
      return undefined;
    });
    vi.stubGlobal("fetch", fetchMock);

    const refetch = vi.fn().mockResolvedValue(undefined);
    const plan = makePlan({ id: "__furniture__", notes: null, elements: [] }, refetch);

    renderControls(plan);

    const brandingItem = await screen.findByText("Branding").then(() => itemFor("Branding"));
    fireEvent.click(within(brandingItem).getByRole("button", { name: "Add" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          (call) =>
            String(call[0]) === "/api/furniture/elements/__furniture_branding" &&
            call[1]?.method === "POST"
        )
      ).toBe(true);
    });
    await waitFor(() => expect(refetch).toHaveBeenCalled());
  });

  it("offers Remove for a configured item and calls the remove route", async () => {
    const fetchMock = stubFetch({ status_indicator: "none" }, {}, (url, method) => {
      if (url === "/api/furniture/elements/__furniture_branding" && method === "DELETE") {
        return Promise.resolve(jsonResponse(200, { element: "__furniture_branding" }));
      }
      return undefined;
    });
    vi.stubGlobal("fetch", fetchMock);

    const refetch = vi.fn().mockResolvedValue(undefined);
    const plan = makePlan(
      { id: "__furniture__", notes: null, elements: [furnitureElement("__furniture_branding")] },
      refetch
    );

    renderControls(plan);

    const brandingItem = await screen.findByText("Branding").then(() => itemFor("Branding"));
    fireEvent.click(within(brandingItem).getByRole("button", { name: "Remove" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          (call) =>
            String(call[0]) === "/api/furniture/elements/__furniture_branding" &&
            call[1]?.method === "DELETE"
        )
      ).toBe(true);
    });
    await waitFor(() => expect(refetch).toHaveBeenCalled());
  });

  it("treats Watermark as a non-entity with no override text, no active render, and no configured style", async () => {
    const fetchMock = stubFetch({ status_indicator: "none" });
    vi.stubGlobal("fetch", fetchMock);

    const plan = makePlan({ id: "__furniture__", notes: null, elements: [] }, vi.fn());
    renderControls(plan);

    await screen.findByText(/select a corner placement in Deck Options to configure/);
    const watermarkItem = itemFor("Watermark");
    expect(within(watermarkItem).queryByRole("button")).not.toBeInTheDocument();
    within(watermarkItem).getByText(
      /select Watermark in Deck Options, or enter a Watermark override above/
    );
  });

  it("offers Add for Watermark once override text is entered, even with a corner active", async () => {
    // The actual reported requirement: a watermark and a corner status
    // indicator must be independently addressable -- Watermark's own
    // Add/Remove never depend on status_indicator at all now, since
    // `__furniture_watermark` is a genuinely separate element.
    const fetchMock = stubFetch(
      { status_indicator: "corner-tl", watermark: "test", metadata: { status: "demo" } },
      {},
      (url, method) => {
        if (url === "/api/furniture/elements/__furniture_watermark" && method === "POST") {
          return Promise.resolve(jsonResponse(200, { element: "__furniture_watermark" }));
        }
        return undefined;
      }
    );
    vi.stubGlobal("fetch", fetchMock);

    const refetch = vi.fn().mockResolvedValue(undefined);
    const plan = makePlan({ id: "__furniture__", notes: null, elements: [] }, refetch);
    renderControls(plan);

    const watermarkItem = await screen.findByText('will show "test"').then(() => itemFor("Watermark"));
    fireEvent.click(within(watermarkItem).getByRole("button", { name: "Add" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          (call) =>
            String(call[0]) === "/api/furniture/elements/__furniture_watermark" &&
            call[1]?.method === "POST"
        )
      ).toBe(true);
    });
    await waitFor(() => expect(refetch).toHaveBeenCalled());
  });

  it("ignores a pre-existing design.yaml watermark style entirely when inactive with no override text", async () => {
    // Regression: an earlier version separately fetched design.yaml and
    // showed "Remove" whenever `furniture.status.watermark` merely
    // *existed* there -- true for a real, previously-built demo project
    // regardless of anything done this session. That made every other
    // action (typing override text, toggling the overlay) look like it
    // did nothing, since the row was already stuck on "Remove" before
    // any of it. A leftover design.yaml style must never influence this
    // row on its own -- only actually being active, or override text
    // having been typed, does.
    const fetchMock = stubFetch({ status_indicator: "corner-tl", watermark: null, metadata: { status: "demo" } });
    vi.stubGlobal("fetch", fetchMock);

    const plan = makePlan({ id: "__furniture__", notes: null, elements: [] }, vi.fn());
    renderControls(plan);

    await screen.findByText("Watermark");
    const watermarkItem = itemFor("Watermark");
    expect(within(watermarkItem).queryByRole("button")).not.toBeInTheDocument();
    within(watermarkItem).getByText(
      /select Watermark in Deck Options, or enter a Watermark override above/
    );
  });

  it("Add succeeds (and activates) even when the underlying style is already configured", async () => {
    // A stale pre-existing style must not block Add with a confusing
    // 422 -- it should just succeed, silently, and activate.
    const fetchMock = stubFetch(
      { status_indicator: "corner-tl", watermark: "test", metadata: { status: "demo" } },
      {},
      (url, method) => {
        if (url === "/api/furniture/elements/__furniture_watermark" && method === "POST") {
          return Promise.resolve(
            jsonResponse(422, {
              code: "E_SCHEMA_VALIDATION",
              message: "design.yaml's furniture.status.watermark is already configured",
            })
          );
        }
        return undefined;
      }
    );
    vi.stubGlobal("fetch", fetchMock);

    const refetch = vi.fn().mockResolvedValue(undefined);
    const plan = makePlan({ id: "__furniture__", notes: null, elements: [] }, refetch);
    renderControls(plan);

    const watermarkItem = await screen.findByText('will show "test"').then(() => itemFor("Watermark"));
    fireEvent.click(within(watermarkItem).getByRole("button", { name: "Add" }));

    await waitFor(() => expect(refetch).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("offers Remove for an active watermark and calls the remove route", async () => {
    // Regression: Remove used to be withheld entirely for status/
    // watermark. `DELETE /api/furniture/elements/__furniture_watermark`
    // now also clears `watermark_overlay` (and `status_indicator` if it
    // was "watermark") server-side in the same action, so a real Remove
    // button here is safe -- confirmed by `test_web.py`'s own server-side
    // test, this one only covers that the button exists and fires.
    const fetchMock = stubFetch({ status_indicator: "watermark" }, {}, (url, method) => {
      if (url === "/api/furniture/elements/__furniture_watermark" && method === "DELETE") {
        return Promise.resolve(jsonResponse(200, { element: "__furniture_watermark" }));
      }
      return undefined;
    });
    vi.stubGlobal("fetch", fetchMock);

    const refetch = vi.fn().mockResolvedValue(undefined);
    const plan = makePlan(
      { id: "__furniture__", notes: null, elements: [furnitureElement("__furniture_watermark")] },
      refetch
    );
    renderControls(plan);

    const watermarkItem = await screen.findByText(/configured/).then(() => itemFor("Watermark"));
    fireEvent.click(within(watermarkItem).getByRole("button", { name: "Remove" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          (call) =>
            String(call[0]) === "/api/furniture/elements/__furniture_watermark" &&
            call[1]?.method === "DELETE"
        )
      ).toBe(true);
    });
    await waitFor(() => expect(refetch).toHaveBeenCalled());
  });

  it("offers a client-only Hide/Show toggle for an active watermark, without touching the network", async () => {
    const fetchMock = stubFetch({ status_indicator: "watermark" });
    vi.stubGlobal("fetch", fetchMock);

    const plan = makePlan(
      { id: "__furniture__", notes: null, elements: [furnitureElement("__furniture_watermark")] },
      vi.fn()
    );
    renderControls(plan);

    const watermarkItem = await screen.findByText(/configured/).then(() => itemFor("Watermark"));
    const hideButton = within(watermarkItem).getByRole("button", { name: "Hide" });
    fireEvent.click(hideButton);
    await within(watermarkItem).findByRole("button", { name: "Show" });
    expect(fetchMock.mock.calls.some((call) => call[1]?.method)).toBe(false);
  });

  it("does not offer Hide for a configured corner placement", async () => {
    const fetchMock = stubFetch({ status_indicator: "corner-tr" });
    vi.stubGlobal("fetch", fetchMock);

    const plan = makePlan(
      { id: "__furniture__", notes: null, elements: [furnitureElement("__furniture_status")] },
      vi.fn()
    );
    renderControls(plan);

    const statusItem = await screen.findByText(/configured/).then(() => itemFor("Status"));
    expect(within(statusItem).queryByRole("button", { name: "Hide" })).not.toBeInTheDocument();
  });

  it("does not offer Hide for background/branding/page-number", async () => {
    const fetchMock = stubFetch({ status_indicator: "none" });
    vi.stubGlobal("fetch", fetchMock);

    const plan = makePlan(
      {
        id: "__furniture__",
        notes: null,
        elements: [
          furnitureElement("__furniture_background"),
          furnitureElement("__furniture_branding"),
          furnitureElement("__furniture_page_number"),
        ],
      },
      vi.fn()
    );
    renderControls(plan);

    await screen.findAllByRole("button", { name: "Remove" });
    expect(screen.queryByRole("button", { name: "Hide" })).not.toBeInTheDocument();
  });

  it("previews the resolved text for Status (Deck status only) before Add is clicked", async () => {
    // Regression: a user typed "test" into what was then a generic
    // "Text" field and had no way to tell it would become the status
    // text until after clicking Add and hunting for it on the canvas.
    const fetchMock = stubFetch({
      status_indicator: "corner-tr",
      watermark: null,
      metadata: { status: "demo" },
    });
    vi.stubGlobal("fetch", fetchMock);

    const plan = makePlan({ id: "__furniture__", notes: null, elements: [] }, vi.fn());
    renderControls(plan);

    const statusItem = await screen.findByText("Status").then(() => itemFor("Status"));
    await within(statusItem).findByText('will show "demo"');
    expect(within(statusItem).getByRole("button", { name: "Add" })).not.toBeDisabled();
  });

  it("disables Add and explains when there is no text to show yet", async () => {
    const fetchMock = stubFetch({ status_indicator: "corner-tr", watermark: null, metadata: {} });
    vi.stubGlobal("fetch", fetchMock);

    const plan = makePlan({ id: "__furniture__", notes: null, elements: [] }, vi.fn());
    renderControls(plan);

    const hint = await screen.findByText(/set Deck status above first/);
    const item = hint.closest(".furniture-controls__item") as HTMLElement;
    expect(within(item).getByRole("button", { name: "Add" })).toBeDisabled();
  });

  it("shows both Watermark and Status as active at once when both are configured", async () => {
    // The actual reported requirement, exercised end to end at the
    // component level: a watermark and a corner status indicator render
    // simultaneously.
    const fetchMock = stubFetch({
      status_indicator: "corner-tl",
      watermark: "test",
      watermark_overlay: true,
      metadata: { status: "demo" },
    });
    vi.stubGlobal("fetch", fetchMock);

    const plan = makePlan(
      {
        id: "__furniture__",
        notes: null,
        elements: [furnitureElement("__furniture_status"), furnitureElement("__furniture_watermark")],
      },
      vi.fn()
    );
    renderControls(plan);

    const watermarkItem = await screen.findByText("Watermark").then(() => itemFor("Watermark"));
    const statusItem = itemFor("Status");
    within(watermarkItem).getByRole("button", { name: "Remove" });
    within(watermarkItem).getByRole("button", { name: "Hide" });
    within(statusItem).getByRole("button", { name: "Remove" });
  });
});
