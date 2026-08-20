import { describe, expect, it } from "vitest";
import { appReducer, initialAppState, type HistoryEntry } from "./reducer";

function entry(overrides: Partial<HistoryEntry> = {}): HistoryEntry {
  return {
    slideId: "slide-1",
    elementId: "el-1",
    patch: { rotation: 45 },
    inverse: { rotation: 0 },
    label: "rotate",
    ...overrides,
  };
}

describe("selection", () => {
  it("selects a slide and clears element selection", () => {
    const withElement = { ...initialAppState, selectedElementId: "el-1" };
    const next = appReducer(withElement, { type: "SELECT_SLIDE", slideId: "slide-2" });
    expect(next.selectedSlideId).toBe("slide-2");
    expect(next.selectedElementId).toBeNull();
  });

  it("selects an element without touching slide selection", () => {
    const withSlide = { ...initialAppState, selectedSlideId: "slide-1" };
    const next = appReducer(withSlide, { type: "SELECT_ELEMENT", elementId: "el-2" });
    expect(next.selectedSlideId).toBe("slide-1");
    expect(next.selectedElementId).toBe("el-2");
  });
});

describe("editorMode", () => {
  it("defaults to slides", () => {
    expect(initialAppState.editorMode).toBe("slides");
  });

  it("sets the mode and clears both selections", () => {
    const selected = { ...initialAppState, selectedSlideId: "slide-1", selectedElementId: "el-1" };
    const next = appReducer(selected, { type: "SET_EDITOR_MODE", mode: "layouts" });
    expect(next.editorMode).toBe("layouts");
    expect(next.selectedSlideId).toBeNull();
    expect(next.selectedElementId).toBeNull();
  });

  it("persists across SELECT_SLIDE, unlike the superseded per-slide toggle", () => {
    const inLayoutsMode = { ...initialAppState, editorMode: "layouts" as const };
    const next = appReducer(inLayoutsMode, { type: "SELECT_SLIDE", slideId: "__layout__blank" });
    expect(next.editorMode).toBe("layouts");
  });
});

describe("showFurniture", () => {
  it("defaults to hidden", () => {
    expect(initialAppState.showFurniture).toBe(false);
  });

  it("toggles independently of every other field", () => {
    const shown = appReducer(initialAppState, { type: "SET_SHOW_FURNITURE", show: true });
    expect(shown.showFurniture).toBe(true);
    expect(shown.selectedSlideId).toBe(initialAppState.selectedSlideId);

    const hiddenAgain = appReducer(shown, { type: "SET_SHOW_FURNITURE", show: false });
    expect(hiddenAgain.showFurniture).toBe(false);
  });
});

describe("dirty", () => {
  it("defaults to clean", () => {
    expect(initialAppState.dirty).toBe(false);
  });

  it("sets independently of every other field", () => {
    const dirty = appReducer(initialAppState, { type: "SET_DIRTY", dirty: true });
    expect(dirty.dirty).toBe(true);
    expect(dirty.selectedSlideId).toBe(initialAppState.selectedSlideId);

    const clean = appReducer(dirty, { type: "SET_DIRTY", dirty: false });
    expect(clean.dirty).toBe(false);
  });
});

describe("hiddenFurnitureIds", () => {
  it("defaults to empty", () => {
    expect(initialAppState.hiddenFurnitureIds).toEqual([]);
  });

  it("toggling an id adds it, toggling again removes it", () => {
    const hidden = appReducer(initialAppState, {
      type: "TOGGLE_FURNITURE_HIDDEN",
      elementId: "__furniture_status",
    });
    expect(hidden.hiddenFurnitureIds).toEqual(["__furniture_status"]);

    const shownAgain = appReducer(hidden, {
      type: "TOGGLE_FURNITURE_HIDDEN",
      elementId: "__furniture_status",
    });
    expect(shownAgain.hiddenFurnitureIds).toEqual([]);
  });

  it("tracks multiple hidden ids independently", () => {
    const first = appReducer(initialAppState, {
      type: "TOGGLE_FURNITURE_HIDDEN",
      elementId: "__furniture_status",
    });
    const both = appReducer(first, {
      type: "TOGGLE_FURNITURE_HIDDEN",
      elementId: "__furniture_branding",
    });
    expect(both.hiddenFurnitureIds).toEqual(["__furniture_status", "__furniture_branding"]);
  });
});

describe("zoom", () => {
  it("sets zoom within range", () => {
    const next = appReducer(initialAppState, { type: "SET_ZOOM", zoom: 2 });
    expect(next.zoom).toBe(2);
  });

  it("clamps zoom to the minimum", () => {
    const next = appReducer(initialAppState, { type: "SET_ZOOM", zoom: -5 });
    expect(next.zoom).toBe(0.1);
  });

  it("clamps zoom to the maximum", () => {
    const next = appReducer(initialAppState, { type: "SET_ZOOM", zoom: 999 });
    expect(next.zoom).toBe(4);
  });
});

describe("history stack", () => {
  it("pushes an entry onto past and clears future", () => {
    const withFuture = { ...initialAppState, future: [entry({ label: "stale redo" })] };
    const next = appReducer(withFuture, { type: "PUSH_HISTORY", entry: entry() });
    expect(next.past).toHaveLength(1);
    expect(next.future).toHaveLength(0);
  });

  it("undo moves the last past entry to the front of future", () => {
    const e1 = entry({ elementId: "el-1" });
    const e2 = entry({ elementId: "el-2" });
    const state = { ...initialAppState, past: [e1, e2] };

    const next = appReducer(state, { type: "UNDO" });

    expect(next.past).toEqual([e1]);
    expect(next.future).toEqual([e2]);
  });

  it("undo on an empty past is a no-op", () => {
    const next = appReducer(initialAppState, { type: "UNDO" });
    expect(next).toBe(initialAppState);
  });

  it("redo moves the front of future back onto past", () => {
    const e1 = entry({ elementId: "el-1" });
    const e2 = entry({ elementId: "el-2" });
    const state = { ...initialAppState, past: [e1], future: [e2] };

    const next = appReducer(state, { type: "REDO" });

    expect(next.past).toEqual([e1, e2]);
    expect(next.future).toEqual([]);
  });

  it("redo on an empty future is a no-op", () => {
    const next = appReducer(initialAppState, { type: "REDO" });
    expect(next).toBe(initialAppState);
  });

  it("undo then redo round-trips back to the same stacks", () => {
    const e1 = entry({ elementId: "el-1" });
    const state = { ...initialAppState, past: [e1] };

    const undone = appReducer(state, { type: "UNDO" });
    const redone = appReducer(undone, { type: "REDO" });

    expect(redone.past).toEqual([e1]);
    expect(redone.future).toEqual([]);
  });

  it("a new PUSH_HISTORY after an undo discards the redo branch", () => {
    const e1 = entry({ elementId: "el-1" });
    const e2 = entry({ elementId: "el-2" });
    const state = { ...initialAppState, past: [e1], future: [e2] };

    const newEdit = entry({ elementId: "el-3" });
    const next = appReducer(state, { type: "PUSH_HISTORY", entry: newEdit });

    expect(next.past).toEqual([e1, newEdit]);
    expect(next.future).toEqual([]);
  });
});
