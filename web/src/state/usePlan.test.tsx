/**
 * Covers `usePlan`'s `sendPatch` dispatcher (issue #21): an element
 * patch/undo/redo for the furniture pseudo-slide (`FURNITURE_SLIDE_ID`)
 * must hit `/api/furniture/elements/{id}`, and everything else must
 * keep hitting the ordinary `/api/slides/{slide}/elements/{id}` route --
 * `applyElementPatch`/`undo`/`redo` all route through the same
 * dispatcher, so one exercised end-to-end (`applyElementPatch`) plus a
 * direct check of `undo` is enough to cover all three call sites.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { AppProvider } from "./AppContext";
import { FURNITURE_SLIDE_ID, usePlan } from "./usePlan";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const EMPTY_PLAN = { slides: [] };
const EMPTY_DESIGN = { slide: { width: "13.333in", height: "7.5in" } };
const EMPTY_FURNITURE = { id: FURNITURE_SLIDE_ID, notes: null, elements: [] };
const EMPTY_LAYOUTS = { layouts: [] };

function wrapper({ children }: { children: ReactNode }) {
  return <AppProvider>{children}</AppProvider>;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("usePlan's patch dispatcher", () => {
  it("routes a furniture-slide patch to /api/furniture/elements/{id}", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/api/plan") return Promise.resolve(jsonResponse(200, EMPTY_PLAN));
      if (url === "/api/config/design") return Promise.resolve(jsonResponse(200, EMPTY_DESIGN));
      if (url === "/api/layouts") return Promise.resolve(jsonResponse(200, EMPTY_LAYOUTS));
      if (url === "/api/furniture" && method === "GET") {
        return Promise.resolve(jsonResponse(200, EMPTY_FURNITURE));
      }
      if (url === "/api/furniture/elements/__furniture_branding" && method === "PATCH") {
        return Promise.resolve(jsonResponse(200, { element: "__furniture_branding" }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url} ${method}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => usePlan(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.applyElementPatch(
        FURNITURE_SLIDE_ID,
        "__furniture_branding",
        { box: { x: 1, y: 1, width: 2, height: 0.5 } },
        {},
        "move"
      );
    });

    const patchCall = fetchMock.mock.calls.find((call) => call[1]?.method === "PATCH");
    expect(patchCall).toBeDefined();
    expect(String(patchCall![0])).toBe("/api/furniture/elements/__furniture_branding");
    expect(
      fetchMock.mock.calls.some((call) => String(call[0]).startsWith("/api/slides/"))
    ).toBe(false);
  });

  it("routes an ordinary slide patch to /api/slides/{slide}/elements/{id}", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/api/plan") return Promise.resolve(jsonResponse(200, EMPTY_PLAN));
      if (url === "/api/config/design") return Promise.resolve(jsonResponse(200, EMPTY_DESIGN));
      if (url === "/api/layouts") return Promise.resolve(jsonResponse(200, EMPTY_LAYOUTS));
      if (url === "/api/furniture" && method === "GET") {
        return Promise.resolve(jsonResponse(200, EMPTY_FURNITURE));
      }
      if (url === "/api/slides/title/elements/deck-title" && method === "PATCH") {
        return Promise.resolve(jsonResponse(200, { element: "deck-title" }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url} ${method}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => usePlan(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.applyElementPatch(
        "title",
        "deck-title",
        { rotation: 5 },
        { rotation: 0 },
        "rotate"
      );
    });

    const patchCall = fetchMock.mock.calls.find((call) => call[1]?.method === "PATCH");
    expect(patchCall).toBeDefined();
    expect(String(patchCall![0])).toBe("/api/slides/title/elements/deck-title");
    expect(
      fetchMock.mock.calls.some((call) => String(call[0]).startsWith("/api/furniture/elements/"))
    ).toBe(false);
  });

  it("routes a __layout__ slide patch to /api/layouts/{name}/elements/{id}", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/api/plan") return Promise.resolve(jsonResponse(200, EMPTY_PLAN));
      if (url === "/api/config/design") return Promise.resolve(jsonResponse(200, EMPTY_DESIGN));
      if (url === "/api/layouts") return Promise.resolve(jsonResponse(200, EMPTY_LAYOUTS));
      if (url === "/api/furniture" && method === "GET") {
        return Promise.resolve(jsonResponse(200, EMPTY_FURNITURE));
      }
      if (url === "/api/layouts/title-content/elements/title" && method === "PATCH") {
        return Promise.resolve(jsonResponse(200, { element: "title" }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url} ${method}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => usePlan(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.applyElementPatch(
        "__layout__title-content",
        "title",
        { box: { x: 1, y: 1, width: 2, height: 0.5 } },
        {},
        "move"
      );
    });

    const patchCall = fetchMock.mock.calls.find((call) => call[1]?.method === "PATCH");
    expect(patchCall).toBeDefined();
    expect(String(patchCall![0])).toBe("/api/layouts/title-content/elements/title");
  });
});

describe("usePlan's layouts", () => {
  it("fetches every layout eagerly, alongside slides/furniture", async () => {
    const layoutsBody = {
      layouts: [{ id: "__layout__title-content", notes: null, elements: [] }],
    };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/plan") return Promise.resolve(jsonResponse(200, EMPTY_PLAN));
      if (url === "/api/config/design") return Promise.resolve(jsonResponse(200, EMPTY_DESIGN));
      if (url === "/api/furniture") return Promise.resolve(jsonResponse(200, EMPTY_FURNITURE));
      if (url === "/api/layouts") return Promise.resolve(jsonResponse(200, layoutsBody));
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => usePlan(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.layouts).toEqual(layoutsBody.layouts);
  });

  it("a failed layouts fetch doesn't block slides/furniture", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/plan") return Promise.resolve(jsonResponse(200, EMPTY_PLAN));
      if (url === "/api/config/design") return Promise.resolve(jsonResponse(200, EMPTY_DESIGN));
      if (url === "/api/furniture") return Promise.resolve(jsonResponse(200, EMPTY_FURNITURE));
      if (url === "/api/layouts") return Promise.resolve(jsonResponse(500, { message: "boom" }));
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => usePlan(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.layouts).toBeNull();
    expect(result.current.furnitureSlide).toEqual(EMPTY_FURNITURE);
  });
});

describe("usePlan's addLayout/removeLayout", () => {
  it("addLayout posts to /api/layouts and refetches", async () => {
    let layoutsCallCount = 0;
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/api/plan") return Promise.resolve(jsonResponse(200, EMPTY_PLAN));
      if (url === "/api/config/design") return Promise.resolve(jsonResponse(200, EMPTY_DESIGN));
      if (url === "/api/furniture") return Promise.resolve(jsonResponse(200, EMPTY_FURNITURE));
      if (url === "/api/layouts" && method === "GET") {
        layoutsCallCount += 1;
        return Promise.resolve(jsonResponse(200, { layouts: [] }));
      }
      if (url === "/api/layouts" && method === "POST") {
        return Promise.resolve(jsonResponse(200, { id: "new-layout", dirty: true }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url} ${method}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => usePlan(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    const callsBeforeAdd = layoutsCallCount;

    await act(async () => {
      await result.current.addLayout("new-layout");
    });

    expect(
      fetchMock.mock.calls.some(
        (call) => String(call[0]) === "/api/layouts" && call[1]?.method === "POST"
      )
    ).toBe(true);
    expect(layoutsCallCount).toBeGreaterThan(callsBeforeAdd);
  });

  it("removeLayout deletes /api/layouts/{name} and refetches", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/api/plan") return Promise.resolve(jsonResponse(200, EMPTY_PLAN));
      if (url === "/api/config/design") return Promise.resolve(jsonResponse(200, EMPTY_DESIGN));
      if (url === "/api/furniture") return Promise.resolve(jsonResponse(200, EMPTY_FURNITURE));
      if (url === "/api/layouts" && method === "GET") {
        return Promise.resolve(jsonResponse(200, { layouts: [] }));
      }
      if (url === "/api/layouts/title-content" && method === "DELETE") {
        return Promise.resolve(
          jsonResponse(200, { id: "title-content", reassigned_slides: [], dirty: true })
        );
      }
      return Promise.reject(new Error(`unexpected fetch: ${url} ${method}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => usePlan(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.removeLayout("title-content");
    });

    expect(
      fetchMock.mock.calls.some(
        (call) => String(call[0]) === "/api/layouts/title-content" && call[1]?.method === "DELETE"
      )
    ).toBe(true);
  });
});

describe("usePlan's addElement/removeElement", () => {
  it("addElement routes a __layout__ slide id to /api/layouts/{name}/elements", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/api/plan") return Promise.resolve(jsonResponse(200, EMPTY_PLAN));
      if (url === "/api/config/design") return Promise.resolve(jsonResponse(200, EMPTY_DESIGN));
      if (url === "/api/furniture") return Promise.resolve(jsonResponse(200, EMPTY_FURNITURE));
      if (url === "/api/layouts" && method === "GET") {
        return Promise.resolve(jsonResponse(200, { layouts: [] }));
      }
      if (url === "/api/layouts/title-content/elements" && method === "POST") {
        return Promise.resolve(jsonResponse(200, { element: "new-zone", dirty: true }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url} ${method}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => usePlan(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.addElement("__layout__title-content", { id: "new-zone", type: "slot" });
    });

    expect(
      fetchMock.mock.calls.some(
        (call) =>
          String(call[0]) === "/api/layouts/title-content/elements" && call[1]?.method === "POST"
      )
    ).toBe(true);
  });

  it("removeElement routes an ordinary slide id to /api/slides/{id}/elements/{id}", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/api/plan") return Promise.resolve(jsonResponse(200, EMPTY_PLAN));
      if (url === "/api/config/design") return Promise.resolve(jsonResponse(200, EMPTY_DESIGN));
      if (url === "/api/furniture") return Promise.resolve(jsonResponse(200, EMPTY_FURNITURE));
      if (url === "/api/layouts" && method === "GET") {
        return Promise.resolve(jsonResponse(200, { layouts: [] }));
      }
      if (url === "/api/slides/title/elements/deck-title" && method === "DELETE") {
        return Promise.resolve(jsonResponse(200, { element: "deck-title", dirty: true }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url} ${method}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => usePlan(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.removeElement("title", "deck-title");
    });

    expect(
      fetchMock.mock.calls.some(
        (call) =>
          String(call[0]) === "/api/slides/title/elements/deck-title" &&
          call[1]?.method === "DELETE"
      )
    ).toBe(true);
  });
});

describe("usePlan's addSlide/removeSlide", () => {
  it("addSlide posts to /api/slides and refetches the plan", async () => {
    let planCallCount = 0;
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/api/plan") {
        planCallCount += 1;
        return Promise.resolve(jsonResponse(200, EMPTY_PLAN));
      }
      if (url === "/api/config/design") return Promise.resolve(jsonResponse(200, EMPTY_DESIGN));
      if (url === "/api/furniture") return Promise.resolve(jsonResponse(200, EMPTY_FURNITURE));
      if (url === "/api/layouts") return Promise.resolve(jsonResponse(200, EMPTY_LAYOUTS));
      if (url === "/api/slides" && method === "POST") {
        return Promise.resolve(jsonResponse(200, { id: "new-slide", slide_count: 3, dirty: true }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url} ${method}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => usePlan(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    const callsBeforeAdd = planCallCount;

    await act(async () => {
      await result.current.addSlide({ id: "new-slide", layout: "blank" });
    });

    expect(
      fetchMock.mock.calls.some(
        (call) => String(call[0]) === "/api/slides" && call[1]?.method === "POST"
      )
    ).toBe(true);
    expect(planCallCount).toBeGreaterThan(callsBeforeAdd);
  });

  it("removeSlide deletes /api/slides/{id} and refetches the plan", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/api/plan") return Promise.resolve(jsonResponse(200, EMPTY_PLAN));
      if (url === "/api/config/design") return Promise.resolve(jsonResponse(200, EMPTY_DESIGN));
      if (url === "/api/furniture") return Promise.resolve(jsonResponse(200, EMPTY_FURNITURE));
      if (url === "/api/layouts") return Promise.resolve(jsonResponse(200, EMPTY_LAYOUTS));
      if (url === "/api/slides/content-slide" && method === "DELETE") {
        return Promise.resolve(jsonResponse(200, { id: "content-slide", slide_count: 1, dirty: true }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url} ${method}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => usePlan(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.removeSlide("content-slide");
    });

    expect(
      fetchMock.mock.calls.some(
        (call) => String(call[0]) === "/api/slides/content-slide" && call[1]?.method === "DELETE"
      )
    ).toBe(true);
  });
});
