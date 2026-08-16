/**
 * Pure state + reducer for selection, zoom, and the undo/redo history
 * stack. Deliberately has no `fetch`/API import at all: applying a
 * history entry's `patch`/`inverse` over the network is the caller's
 * job (see `App.tsx`'s `undo`/`redo` functions) -- this module only
 * tracks *what* to apply, so it's covered by a plain unit test with no
 * mocked network or React rendering involved.
 */

import type { ElementPatchBody } from "../types";

export interface HistoryEntry {
  slideId: string;
  elementId: string;
  /** The patch that was actually sent to the server. */
  patch: ElementPatchBody;
  /** The patch that undoes it -- the affected fields' *previous* values,
   * computed by the caller from the element's state right before
   * `patch` was applied. */
  inverse: ElementPatchBody;
  /** Short human-readable label for the history stack UI ("move",
   * "resize", "rotate", "edit text"). */
  label: string;
}

export interface AppState {
  selectedSlideId: string | null;
  selectedElementId: string | null;
  /** 1 = 100%. Clamped to [0.1, 4] by the reducer so a runaway scroll-
   * wheel handler can't zoom the canvas to nothing or to an unusable
   * size. */
  zoom: number;
  past: HistoryEntry[];
  future: HistoryEntry[];
  /** Purely a canvas *rendering* choice, never sent to the server --
   * distinct from `DeckOptions`' `status_indicator` toggle, which
   * actually turns the watermark/status placement on or off in
   * `presentation.yaml` for the built deck. This one just hides
   * `__furniture_*` elements (background/status/branding/page number)
   * from `SlideCanvas` so they stop sitting on top of (or under) the
   * real content you're trying to select/drag -- default `false`
   * (hidden) since that obstruction, not merely wanting to peek at
   * furniture placement, is the actual day-to-day editing complaint
   * this exists for. */
  showFurniture: boolean;
  /** Furniture element ids hidden from view *while on the furniture
   * pseudo-slide itself* (issue #21 follow-up) -- a separate concern
   * from `showFurniture` above, which only affects furniture rendered
   * on top of *real* slides. A large diagonal watermark can visually
   * bury the much smaller branding/page-number boxes on the furniture
   * pseudo-slide; this lets a user hide it there without touching
   * `design.yaml` at all -- purely client-side, never sent to the
   * server, and intentionally distinct from `FurnitureControls`'
   * "Remove" (which deletes the configured style) or `DeckOptions`'
   * `status_indicator` (which changes what the *built* deck shows).
   * Reset takes care of itself: it's plain in-memory state, gone on
   * reload, and a hidden id that no longer exists (e.g. after Remove)
   * is simply inert. */
  hiddenFurnitureIds: string[];
  /** Content vs Layout view for the selected *real* slide (issue #23's
   * Content/Layout tab) -- "layout" shows/edits the selected slide's own
   * named layout's zones (`layouts.yaml`) instead of the slide's own
   * content, using the same drag/resize/rotate canvas. Always resets to
   * `"content"` on `SELECT_SLIDE` (same reasoning `selectedElementId`
   * already resets there): a layout name from the previously-selected
   * slide isn't meaningful for the new one, and the furniture
   * pseudo-slide has no layout of its own to show. Purely a client-side
   * view mode, like `showFurniture` -- never sent to the server on its
   * own; it only decides which `GET`/`PATCH` target `usePlan` uses. */
  slideViewMode: "content" | "layout";
  /** Whether the server's in-memory working copy (issue #24's deferred-
   * save editor) currently differs from what's on disk. Lives here, not
   * in `usePlan`'s own local state, specifically because it must survive
   * switching away from the Editor tab -- `EditorTab`/`usePlan()` unmount
   * on every tab change (`App.tsx`), but config edits made from the
   * Config tab need to keep the header's Save button/close-warning live
   * too. Every mutating fetch (`usePlan`'s `applyElementPatch`/`undo`/
   * `redo`, `ConfigEditor`'s Apply, `DeckOptions`, `FurnitureControls`)
   * dispatches `SET_DIRTY` with the `dirty` field its own response
   * already carries -- no separate polling loop. */
  dirty: boolean;
}

export const initialAppState: AppState = {
  selectedSlideId: null,
  selectedElementId: null,
  zoom: 1,
  past: [],
  future: [],
  showFurniture: false,
  hiddenFurnitureIds: [],
  slideViewMode: "content",
  dirty: false,
};

export type AppAction =
  | { type: "SELECT_SLIDE"; slideId: string | null }
  | { type: "SELECT_ELEMENT"; elementId: string | null }
  | { type: "SET_ZOOM"; zoom: number }
  | { type: "PUSH_HISTORY"; entry: HistoryEntry }
  | { type: "UNDO" }
  | { type: "REDO" }
  | { type: "SET_SHOW_FURNITURE"; show: boolean }
  | { type: "TOGGLE_FURNITURE_HIDDEN"; elementId: string }
  | { type: "SET_SLIDE_VIEW_MODE"; mode: "content" | "layout" }
  | { type: "SET_DIRTY"; dirty: boolean };

const MIN_ZOOM = 0.1;
const MAX_ZOOM = 4;

export function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case "SELECT_SLIDE":
      // Changing slides always clears element selection -- a selected
      // element id from the previous slide isn't meaningful on the new
      // one (ids aren't guaranteed unique across slides) -- and always
      // resets back to Content view (see `slideViewMode`'s own docstring
      // above for why).
      return {
        ...state,
        selectedSlideId: action.slideId,
        selectedElementId: null,
        slideViewMode: "content",
      };

    case "SELECT_ELEMENT":
      return { ...state, selectedElementId: action.elementId };

    case "SET_ZOOM":
      return { ...state, zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, action.zoom)) };

    case "PUSH_HISTORY":
      // A fresh edit invalidates whatever redo history existed --
      // standard undo-stack semantics (matches browser/editor
      // convention: redo only replays edits that were themselves just
      // undone, not edits from before a divergent new edit).
      return { ...state, past: [...state.past, action.entry], future: [] };

    case "UNDO": {
      if (state.past.length === 0) return state;
      const entry = state.past[state.past.length - 1];
      return {
        ...state,
        past: state.past.slice(0, -1),
        future: [entry, ...state.future],
      };
    }

    case "REDO": {
      if (state.future.length === 0) return state;
      const [entry, ...rest] = state.future;
      return { ...state, past: [...state.past, entry], future: rest };
    }

    case "SET_SHOW_FURNITURE":
      return { ...state, showFurniture: action.show };

    case "SET_SLIDE_VIEW_MODE":
      return { ...state, slideViewMode: action.mode, selectedElementId: null };

    case "SET_DIRTY":
      return { ...state, dirty: action.dirty };

    case "TOGGLE_FURNITURE_HIDDEN":
      return {
        ...state,
        hiddenFurnitureIds: state.hiddenFurnitureIds.includes(action.elementId)
          ? state.hiddenFurnitureIds.filter((id) => id !== action.elementId)
          : [...state.hiddenFurnitureIds, action.elementId],
      };

    default:
      return state;
  }
}
