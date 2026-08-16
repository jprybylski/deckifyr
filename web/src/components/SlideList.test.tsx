import { describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach } from "vitest";
import SlideList from "./SlideList";
import { AppProvider } from "../state/AppContext";
import type { UsePlanResult } from "../state/usePlan";
import type { ResolvedSlide } from "../types";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function makePlan(overrides: Partial<UsePlanResult>): UsePlanResult {
  return {
    slides: null,
    furnitureSlide: null,
    slideLayouts: {},
    layoutSlide: null,
    layoutError: null,
    loadLayoutZones: vi.fn(),
    slideSize: null,
    loading: false,
    error: null,
    refetch: vi.fn(),
    addSlide: vi.fn(),
    removeSlide: vi.fn(),
    applyElementPatch: vi.fn(),
    undo: vi.fn(),
    redo: vi.fn(),
    canUndo: false,
    canRedo: false,
    ...overrides,
  };
}

function renderList(plan: UsePlanResult) {
  return render(
    <AppProvider>
      <SlideList plan={plan} />
    </AppProvider>
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const FURNITURE: ResolvedSlide = { id: "__furniture__", notes: null, elements: [] };
const SLIDE: ResolvedSlide = { id: "title", notes: null, elements: [] };

describe("SlideList", () => {
  it("keeps the Furniture entry reachable when the real-slide plan fails to load", () => {
    // Regression: a real user hit this directly -- picking a
    // status_indicator placement design.yaml hadn't configured yet made
    // GET /api/plan fail, and an earlier version of this component
    // returned early on `error`, discarding the whole list including the
    // one entry (Furniture) that could actually fix the problem. Once
    // that happened without already being on the Furniture slide, there
    // was no way back in short of editing YAML by hand -- the editor
    // read as locked, even though GET /api/furniture (deliberately
    // lenient about exactly this case) had already succeeded.
    const plan = makePlan({
      slides: null,
      furnitureSlide: FURNITURE,
      error: "presentation.yaml sets status_indicator: 'corner-tl', but design.yaml's furniture.status has no 'corner_tl' configured",
    });

    renderList(plan);

    expect(screen.getByText(/⚙ Furniture/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/corner_tl/);
  });

  it("keeps already-loaded real slides visible alongside the error banner", () => {
    const plan = makePlan({
      slides: [SLIDE],
      furnitureSlide: FURNITURE,
      error: "some later, unrelated plan failure",
    });

    renderList(plan);

    expect(screen.getByText(/⚙ Furniture/)).toBeInTheDocument();
    expect(screen.getByText(/1\. title/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/unrelated plan failure/);
  });

  it("renders the ordinary list with no error banner when nothing is wrong", () => {
    const plan = makePlan({ slides: [SLIDE], furnitureSlide: FURNITURE });

    renderList(plan);

    expect(screen.getByText(/⚙ Furniture/)).toBeInTheDocument();
    expect(screen.getByText(/1\. title/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows only the error, with nothing to click, when even the lenient furniture fetch failed", () => {
    const plan = makePlan({ slides: null, furnitureSlide: null, error: "server unreachable" });

    renderList(plan);

    expect(screen.getByText("server unreachable")).toBeInTheDocument();
    expect(screen.queryByText(/⚙ Furniture/)).not.toBeInTheDocument();
  });
});

describe("SlideList add/remove (issue #23)", () => {
  it("opens the add-slide form, fetches layout options, and submits a new slide", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/config/layouts") {
        return Promise.resolve(
          jsonResponse(200, { deckifyr: "0.1", layouts: { "title-content": {}, blank: {} } })
        );
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const addSlide = vi.fn().mockResolvedValue(undefined);
    const plan = makePlan({ slides: [SLIDE], furnitureSlide: FURNITURE, addSlide });
    renderList(plan);

    fireEvent.click(screen.getByText("+ Add slide"));
    await waitFor(() => expect(screen.getByText("title-content")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("New slide id"), {
      target: { value: "new-slide" },
    });
    fireEvent.change(screen.getByLabelText("Layout"), { target: { value: "title-content" } });
    fireEvent.click(screen.getByText("Add"));

    await waitFor(() =>
      expect(addSlide).toHaveBeenCalledWith({ id: "new-slide", layout: "title-content" })
    );
    // Form closes on success.
    await waitFor(() => expect(screen.queryByLabelText("New slide id")).not.toBeInTheDocument());
  });

  it("defaults to a freeform (null) layout when none is picked", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { layouts: {} }));
    vi.stubGlobal("fetch", fetchMock);

    const addSlide = vi.fn().mockResolvedValue(undefined);
    const plan = makePlan({ slides: [SLIDE], furnitureSlide: FURNITURE, addSlide });
    renderList(plan);

    fireEvent.click(screen.getByText("+ Add slide"));
    fireEvent.change(screen.getByLabelText("New slide id"), {
      target: { value: "freeform-slide" },
    });
    fireEvent.click(screen.getByText("Add"));

    await waitFor(() =>
      expect(addSlide).toHaveBeenCalledWith({ id: "freeform-slide", layout: null })
    );
  });

  it("shows a two-step confirm before removing a slide, cancel keeps it", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, { layouts: {} })));
    const removeSlide = vi.fn();
    const plan = makePlan({ slides: [SLIDE], furnitureSlide: FURNITURE, removeSlide });
    renderList(plan);

    fireEvent.click(screen.getByTitle('Remove slide "title"'));
    expect(screen.getByText(/Remove .title.\?/)).toBeInTheDocument();
    expect(removeSlide).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("Cancel"));
    expect(screen.queryByText(/Remove .title.\?/)).not.toBeInTheDocument();
    expect(removeSlide).not.toHaveBeenCalled();
  });

  it("removes a slide after Confirm", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, { layouts: {} })));
    const removeSlide = vi.fn().mockResolvedValue(undefined);
    const plan = makePlan({ slides: [SLIDE], furnitureSlide: FURNITURE, removeSlide });
    renderList(plan);

    fireEvent.click(screen.getByTitle('Remove slide "title"'));
    fireEvent.click(screen.getByText("Confirm"));

    await waitFor(() => expect(removeSlide).toHaveBeenCalledWith("title"));
  });
});
