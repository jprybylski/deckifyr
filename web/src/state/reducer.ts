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
}

export const initialAppState: AppState = {
  selectedSlideId: null,
  selectedElementId: null,
  zoom: 1,
  past: [],
  future: [],
  showFurniture: false,
};

export type AppAction =
  | { type: "SELECT_SLIDE"; slideId: string | null }
  | { type: "SELECT_ELEMENT"; elementId: string | null }
  | { type: "SET_ZOOM"; zoom: number }
  | { type: "PUSH_HISTORY"; entry: HistoryEntry }
  | { type: "UNDO" }
  | { type: "REDO" }
  | { type: "SET_SHOW_FURNITURE"; show: boolean };

const MIN_ZOOM = 0.1;
const MAX_ZOOM = 4;

export function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case "SELECT_SLIDE":
      // Changing slides always clears element selection -- a selected
      // element id from the previous slide isn't meaningful on the new
      // one (ids aren't guaranteed unique across slides).
      return { ...state, selectedSlideId: action.slideId, selectedElementId: null };

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

    default:
      return state;
  }
}
