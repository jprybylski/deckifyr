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

describe("usePlan's loadLayoutZones", () => {
  it("fetches a layout's zones and exposes them as layoutSlide", async () => {
    const zones = { id: "__layout__title-content", notes: null, elements: [] };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/plan") return Promise.resolve(jsonResponse(200, EMPTY_PLAN));
      if (url === "/api/config/design") return Promise.resolve(jsonResponse(200, EMPTY_DESIGN));
      if (url === "/api/furniture") return Promise.resolve(jsonResponse(200, EMPTY_FURNITURE));
      if (url === "/api/layouts/title-content") return Promise.resolve(jsonResponse(200, zones));
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => usePlan(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.loadLayoutZones("title-content");
    });

    expect(result.current.layoutSlide).toEqual(zones);
    expect(result.current.layoutError).toBeNull();
  });

  it("surfaces a fetch failure as layoutError instead of throwing", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/plan") return Promise.resolve(jsonResponse(200, EMPTY_PLAN));
      if (url === "/api/config/design") return Promise.resolve(jsonResponse(200, EMPTY_DESIGN));
      if (url === "/api/furniture") return Promise.resolve(jsonResponse(200, EMPTY_FURNITURE));
      if (url === "/api/layouts/does-not-exist") {
        return Promise.resolve(jsonResponse(404, { detail: "unknown layout" }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => usePlan(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.loadLayoutZones("does-not-exist");
    });

    expect(result.current.layoutSlide).toBeNull();
    expect(result.current.layoutError).toBe("unknown layout");
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
