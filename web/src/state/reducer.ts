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
}

export const initialAppState: AppState = {
  selectedSlideId: null,
  selectedElementId: null,
  zoom: 1,
  past: [],
  future: [],
};

export type AppAction =
  | { type: "SELECT_SLIDE"; slideId: string | null }
  | { type: "SELECT_ELEMENT"; elementId: string | null }
  | { type: "SET_ZOOM"; zoom: number }
  | { type: "PUSH_HISTORY"; entry: HistoryEntry }
  | { type: "UNDO" }
  | { type: "REDO" };

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

    default:
      return state;
  }
}
