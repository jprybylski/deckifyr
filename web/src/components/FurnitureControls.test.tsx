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

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

describe("FurnitureControls", () => {
  it("offers Add for an unconfigured branding item and calls the add route", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, { status_indicator: "none" }));
      }
      if (url === "/api/furniture/elements/__furniture_branding" && method === "POST") {
        return Promise.resolve(jsonResponse(200, { element: "__furniture_branding" }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url} ${method}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const refetch = vi.fn().mockResolvedValue(undefined);
    const plan = makePlan(
      { id: "__furniture__", notes: null, elements: [] },
      refetch
    );

    renderControls(plan);

    const addButtons = await screen.findAllByRole("button", { name: "Add" });
    // Branding, page number -- status has no Add button yet since no
    // placement is selected (status_indicator: "none").
    expect(addButtons.length).toBe(2);
    fireEvent.click(addButtons[0]);

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
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, { status_indicator: "none" }));
      }
      if (url === "/api/furniture/elements/__furniture_branding" && method === "DELETE") {
        return Promise.resolve(jsonResponse(200, { element: "__furniture_branding" }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url} ${method}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const refetch = vi.fn().mockResolvedValue(undefined);
    const plan = makePlan(
      { id: "__furniture__", notes: null, elements: [furnitureElement("__furniture_branding")] },
      refetch
    );

    renderControls(plan);

    const removeButton = await screen.findByRole("button", { name: "Remove" });
    fireEvent.click(removeButton);

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

  it("shows a hint instead of an Add button for status when no placement is selected", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, { status_indicator: "none" }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const plan = makePlan({ id: "__furniture__", notes: null, elements: [] }, vi.fn());
    renderControls(plan);

    await screen.findByText(/choose a placement in Deck Options first/);
  });

  it("never offers Remove for a configured status placement", async () => {
    // Regression: status always resolves to whichever placement
    // status_indicator currently selects, so a Remove button here would
    // delete the *active* placement's style while presentation.yaml
    // still points at it -- breaking every slide's plan, not just this
    // pseudo-slide (a real bug this test would have caught).
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, { status_indicator: "watermark" }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const plan = makePlan(
      { id: "__furniture__", notes: null, elements: [furnitureElement("__furniture_status")] },
      vi.fn()
    );
    renderControls(plan);

    await screen.findByText(/set Status\/watermark to None above/);
    expect(screen.queryAllByRole("button", { name: "Remove" })).toHaveLength(0);
  });

  it("offers a client-only Hide/Show toggle for an active watermark, without touching the network", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, { status_indicator: "watermark" }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const plan = makePlan(
      { id: "__furniture__", notes: null, elements: [furnitureElement("__furniture_status")] },
      vi.fn()
    );
    renderControls(plan);

    const hideButton = await screen.findByRole("button", { name: "Hide" });
    fireEvent.click(hideButton);
    await screen.findByRole("button", { name: "Show" });
    expect(fetchMock.mock.calls.some((call) => call[1]?.method)).toBe(false);
  });

  it("does not offer Hide for a configured corner placement", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, { status_indicator: "corner-tr" }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const plan = makePlan(
      { id: "__furniture__", notes: null, elements: [furnitureElement("__furniture_status")] },
      vi.fn()
    );
    renderControls(plan);

    await screen.findByText(/set Status\/watermark to None above/);
    expect(screen.queryByRole("button", { name: "Hide" })).not.toBeInTheDocument();
  });

  it("does not offer Hide for background/branding/page-number", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, { status_indicator: "none" }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
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

  it("previews the resolved text (watermark override, or Deck status) before Add is clicked", async () => {
    // Regression: a user typed "test" into what was then a generic
    // "Text" field and had no way to tell it would become the status
    // text until after clicking Add and hunting for it on the canvas.
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/config/presentation") {
        return Promise.resolve(
          jsonResponse(200, {
            status_indicator: "corner-tr",
            watermark: null,
            metadata: { status: "demo" },
          })
        );
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const plan = makePlan({ id: "__furniture__", notes: null, elements: [] }, vi.fn());
    renderControls(plan);

    const hint = await screen.findByText('will show "demo"');
    const item = hint.closest(".furniture-controls__item") as HTMLElement;
    expect(within(item).getByRole("button", { name: "Add" })).not.toBeDisabled();
  });

  it("disables Add and explains when there is no text to show yet", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/config/presentation") {
        return Promise.resolve(
          jsonResponse(200, { status_indicator: "corner-tr", watermark: null, metadata: {} })
        );
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const plan = makePlan({ id: "__furniture__", notes: null, elements: [] }, vi.fn());
    renderControls(plan);

    const hint = await screen.findByText(/set Deck status above first/);
    const item = hint.closest(".furniture-controls__item") as HTMLElement;
    expect(within(item).getByRole("button", { name: "Add" })).toBeDisabled();
  });
});
