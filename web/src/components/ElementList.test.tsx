import { useEffect, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import ElementList from "./ElementList";
import { AppProvider, useAppContext } from "../state/AppContext";
import type { UsePlanResult } from "../state/usePlan";
import type { ResolvedElement, ResolvedSlide } from "../types";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function element(overrides: Partial<ResolvedElement>): ResolvedElement {
  return {
    id: "el",
    type: "text",
    value: null,
    source: null,
    box: { x: "0in", y: "0in", width: "1in", height: "1in" },
    rotation: 0,
    z_index: 0,
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
    ...overrides,
  };
}

function makePlan(overrides: Partial<UsePlanResult>): UsePlanResult {
  return {
    slides: null,
    furnitureSlide: null,
    slideLayouts: {},
    layouts: null,
    slideSize: { widthIn: 13.333, heightIn: 7.5 },
    loading: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
    addSlide: vi.fn(),
    removeSlide: vi.fn(),
    duplicateSlide: vi.fn(),
    addLayout: vi.fn(),
    removeLayout: vi.fn(),
    addElement: vi.fn().mockResolvedValue(undefined),
    removeElement: vi.fn().mockResolvedValue(undefined),
    applyElementPatch: vi.fn(),
    undo: vi.fn(),
    redo: vi.fn(),
    canUndo: false,
    canRedo: false,
    ...overrides,
  };
}

/** Selects `slideId` on mount, the same `SELECT_SLIDE` dispatch clicking
 * a `SlideList` row would fire -- `ElementList` derives which slide/
 * furniture/layout it shows entirely from shared `AppContext` state, so
 * tests need this instead of a prop. */
function Selected({ slideId, children }: { slideId: string; children: ReactNode }) {
  const { dispatch } = useAppContext();
  useEffect(() => {
    dispatch({ type: "SELECT_SLIDE", slideId });
  }, [slideId, dispatch]);
  return <>{children}</>;
}

function renderList(
  plan: UsePlanResult,
  slideId: string,
  onStatusIndicatorChanged?: () => void
) {
  return render(
    <AppProvider>
      <Selected slideId={slideId}>
        <ElementList plan={plan} onStatusIndicatorChanged={onStatusIndicatorChanged} />
      </Selected>
    </AppProvider>
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const FURNITURE_ID = "__furniture__";

function itemFor(labelText: string | RegExp): HTMLElement {
  return screen.getByText(labelText).closest(".element-list__item") as HTMLElement;
}

describe("ElementList on an ordinary slide", () => {
  const SLIDE: ResolvedSlide = {
    id: "title",
    notes: null,
    elements: [
      element({ id: "deck-title", type: "text" }),
      element({ id: "__furniture_background", type: "image" }),
    ],
  };

  it("lists the slide's own elements, excluding furniture", () => {
    const plan = makePlan({ slides: [SLIDE] });
    renderList(plan, "title");

    expect(screen.getByText("text: deck-title")).toBeInTheDocument();
    expect(screen.queryByText(/__furniture_background/)).not.toBeInTheDocument();
  });

  it("selecting a row expands the inline ElementInspector form", () => {
    const plan = makePlan({ slides: [SLIDE] });
    renderList(plan, "title");

    expect(screen.queryByLabelText("X (in)")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("text: deck-title"));

    expect(screen.getByText("deck-title")).toBeInTheDocument();
    expect(screen.getByLabelText("X (in)")).toBeInTheDocument();
  });

  it("Remove calls plan.removeElement with the slide and element id", async () => {
    const removeElement = vi.fn().mockResolvedValue(undefined);
    const plan = makePlan({ slides: [SLIDE], removeElement });
    renderList(plan, "title");

    fireEvent.click(within(itemFor("text: deck-title")).getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(removeElement).toHaveBeenCalledWith("title", "deck-title"));
  });

  it("adds a new text element via the Add form", async () => {
    const addElement = vi.fn().mockResolvedValue(undefined);
    const plan = makePlan({ slides: [SLIDE], addElement });
    renderList(plan, "title");

    fireEvent.click(screen.getByText("+ Add element"));
    fireEvent.change(screen.getByLabelText("New element id"), {
      target: { value: "new-el" },
    });
    fireEvent.change(screen.getByLabelText("Value"), { target: { value: "hello" } });
    fireEvent.click(screen.getByText("Add"));

    await waitFor(() =>
      expect(addElement).toHaveBeenCalledWith("title", {
        id: "new-el",
        type: "text",
        value: "hello",
      })
    );
  });

  it("disables Add when the id is already used on this slide", () => {
    const plan = makePlan({ slides: [SLIDE] });
    renderList(plan, "title");

    fireEvent.click(screen.getByText("+ Add element"));
    fireEvent.change(screen.getByLabelText("New element id"), {
      target: { value: "deck-title" },
    });

    expect(screen.getByText("Add")).toBeDisabled();
  });

  it("routes a .csv reportifyr artifact pick to a native table element", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/project/files?type=reportifyr") {
        return Promise.resolve(
          jsonResponse(200, { files: ["pk-summary.csv", "conc-time.png"] })
        );
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const addElement = vi.fn().mockResolvedValue(undefined);
    const plan = makePlan({ slides: [SLIDE], addElement });
    renderList(plan, "title");

    fireEvent.click(screen.getByText("+ Add element"));
    fireEvent.change(screen.getByLabelText("New element id"), {
      target: { value: "tbl" },
    });
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "reportifyr" } });
    await screen.findByText("pk-summary.csv");
    fireEvent.change(screen.getByLabelText("Reportifyr artifact"), {
      target: { value: "pk-summary.csv" },
    });
    fireEvent.click(screen.getByText("Add"));

    await waitFor(() =>
      expect(addElement).toHaveBeenCalledWith("title", {
        id: "tbl",
        type: "table",
        source: "{rpfy}:pk-summary.csv",
      })
    );
  });

  it("keeps a non-table reportifyr artifact pick as a reportifyr picture element", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/project/files?type=reportifyr") {
        return Promise.resolve(
          jsonResponse(200, { files: ["conc-time.png", "pk-flextable-summary.rds"] })
        );
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const addElement = vi.fn().mockResolvedValue(undefined);
    const plan = makePlan({ slides: [SLIDE], addElement });
    renderList(plan, "title");

    fireEvent.click(screen.getByText("+ Add element"));
    fireEvent.change(screen.getByLabelText("New element id"), {
      target: { value: "flex" },
    });
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "reportifyr" } });
    await screen.findByText("pk-flextable-summary.rds");
    fireEvent.change(screen.getByLabelText("Reportifyr artifact"), {
      target: { value: "pk-flextable-summary.rds" },
    });
    fireEvent.click(screen.getByText("Add"));

    await waitFor(() =>
      expect(addElement).toHaveBeenCalledWith("title", {
        id: "flex",
        type: "reportifyr",
        value: "{rpfy}:pk-flextable-summary.rds",
      })
    );
  });
});

describe("ElementList on the furniture pseudo-slide", () => {
  function furnitureElement(id: string): ResolvedElement {
    return element({ id, z_index: -10 });
  }

  function stubFetch(
    presentation: Record<string, unknown>,
    extra: (url: string, method: string) => Promise<Response> | undefined = () => undefined
  ) {
    return vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/api/config/presentation" && method === "GET") {
        return Promise.resolve(jsonResponse(200, presentation));
      }
      const handled = extra(url, method);
      if (handled) return handled;
      return Promise.reject(new Error(`unexpected fetch: ${url} ${method}`));
    });
  }

  it("offers Add for an unconfigured branding row and calls the add route", async () => {
    const fetchMock = stubFetch({ status_indicator: "none" }, (url, method) => {
      if (url === "/api/furniture/elements/__furniture_branding" && method === "POST") {
        return Promise.resolve(jsonResponse(200, { element: "__furniture_branding" }));
      }
      return undefined;
    });
    vi.stubGlobal("fetch", fetchMock);

    const refetch = vi.fn().mockResolvedValue(undefined);
    const plan = makePlan({ furnitureSlide: { id: FURNITURE_ID, notes: null, elements: [] }, refetch });
    renderList(plan, FURNITURE_ID);

    const brandingItem = await screen.findByText("Branding").then(() => itemFor("Branding"));
    fireEvent.click(within(brandingItem).getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          (call) =>
            String(call[0]) === "/api/furniture/elements/__furniture_branding" &&
            call[1]?.method === "POST"
        )
      ).toBe(true)
    );
    await waitFor(() => expect(refetch).toHaveBeenCalled());
  });

  it("offers Remove for a configured item and calls the remove route", async () => {
    const fetchMock = stubFetch({ status_indicator: "none" }, (url, method) => {
      if (url === "/api/furniture/elements/__furniture_branding" && method === "DELETE") {
        return Promise.resolve(jsonResponse(200, { element: "__furniture_branding" }));
      }
      return undefined;
    });
    vi.stubGlobal("fetch", fetchMock);

    const refetch = vi.fn().mockResolvedValue(undefined);
    const plan = makePlan({
      furnitureSlide: {
        id: FURNITURE_ID,
        notes: null,
        elements: [furnitureElement("__furniture_branding")],
      },
      refetch,
    });
    renderList(plan, FURNITURE_ID);

    const brandingItem = await screen.findByText("Branding").then(() => itemFor("Branding"));
    fireEvent.click(within(brandingItem).getByRole("button", { name: "Remove" }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          (call) =>
            String(call[0]) === "/api/furniture/elements/__furniture_branding" &&
            call[1]?.method === "DELETE"
        )
      ).toBe(true)
    );
    await waitFor(() => expect(refetch).toHaveBeenCalled());
  });

  it("Add for Status defaults to the watermark placement when nothing is selected yet", async () => {
    const fetchMock = stubFetch(
      { status_indicator: null, watermark: "test", metadata: { status: "demo" } },
      (url, method) => {
        if (url === "/api/furniture/elements/__furniture_status" && method === "POST") {
          return Promise.resolve(jsonResponse(200, { element: "__furniture_status" }));
        }
        return undefined;
      }
    );
    vi.stubGlobal("fetch", fetchMock);

    const refetch = vi.fn().mockResolvedValue(undefined);
    const plan = makePlan({ furnitureSlide: { id: FURNITURE_ID, notes: null, elements: [] }, refetch });
    renderList(plan, FURNITURE_ID);

    const statusItem = await screen.findByText(/will show "test"/).then(() => itemFor(/^Status$/));
    fireEvent.click(within(statusItem).getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          (call) =>
            String(call[0]) === "/api/furniture/elements/__furniture_status" &&
            call[1]?.method === "POST"
        )
      ).toBe(true)
    );
  });

  it("calls onStatusIndicatorChanged after Status Add/Remove, never for other kinds", async () => {
    const fetchMock = stubFetch({ status_indicator: null, metadata: { status: "demo" } }, (url, method) => {
      if (url === "/api/furniture/elements/__furniture_status" && method === "POST") {
        return Promise.resolve(jsonResponse(200, { element: "__furniture_status" }));
      }
      if (url === "/api/furniture/elements/__furniture_branding" && method === "POST") {
        return Promise.resolve(jsonResponse(200, { element: "__furniture_branding" }));
      }
      return undefined;
    });
    vi.stubGlobal("fetch", fetchMock);

    const onStatusIndicatorChanged = vi.fn();
    const plan = makePlan({ furnitureSlide: { id: FURNITURE_ID, notes: null, elements: [] } });
    renderList(plan, FURNITURE_ID, onStatusIndicatorChanged);

    const brandingItem = await screen.findByText("Branding").then(() => itemFor("Branding"));
    fireEvent.click(within(brandingItem).getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some((call) => String(call[0]).includes("__furniture_branding"))
      ).toBe(true)
    );
    expect(onStatusIndicatorChanged).not.toHaveBeenCalled();

    const statusItem = itemFor(/Status/);
    fireEvent.click(within(statusItem).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(onStatusIndicatorChanged).toHaveBeenCalledTimes(1));
  });

  it("offers a client-only Hide/Show toggle only while the active placement is the watermark", async () => {
    const fetchMock = stubFetch({ status_indicator: "watermark" });
    vi.stubGlobal("fetch", fetchMock);

    const plan = makePlan({
      furnitureSlide: {
        id: FURNITURE_ID,
        notes: null,
        elements: [furnitureElement("__furniture_status")],
      },
    });
    renderList(plan, FURNITURE_ID);

    const statusItem = await screen.findByText(/Status/).then(() => itemFor(/Status/));
    const hideButton = within(statusItem).getByRole("button", { name: "Hide" });
    fireEvent.click(hideButton);
    await within(statusItem).findByRole("button", { name: "Show" });
    expect(fetchMock.mock.calls.some((call) => (call[1] as RequestInit | undefined)?.method)).toBe(
      false
    );
  });

  it("the background row has no Add/Remove of its own, just a Config-tab hint", async () => {
    const fetchMock = stubFetch({ status_indicator: "none" });
    vi.stubGlobal("fetch", fetchMock);

    const plan = makePlan({ furnitureSlide: { id: FURNITURE_ID, notes: null, elements: [] } });
    renderList(plan, FURNITURE_ID);

    const backgroundItem = await screen.findByText("Background").then(() => itemFor("Background"));
    expect(within(backgroundItem).queryByRole("button", { name: "Add" })).not.toBeInTheDocument();
    expect(within(backgroundItem).getByText(/not set -- edit via Config tab/)).toBeInTheDocument();
  });
});
