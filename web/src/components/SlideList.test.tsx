import { describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach } from "vitest";
import SlideList from "./SlideList";
import { AppProvider } from "../state/AppContext";
import type { UsePlanResult } from "../state/usePlan";
import type { ResolvedSlide } from "../types";

function makePlan(overrides: Partial<UsePlanResult>): UsePlanResult {
  return {
    slides: null,
    furnitureSlide: null,
    slideSize: null,
    loading: false,
    error: null,
    refetch: vi.fn(),
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

afterEach(() => cleanup());

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
