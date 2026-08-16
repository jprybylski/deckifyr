/** Zoom control + undo/redo + the Content/Layout view toggle (issue
 * #23). Undo/redo delegate to `usePlan`'s `undo`/`redo` (which replay a
 * `HistoryEntry`'s `inverse`/`patch` over the network and refetch) --
 * this component only surfaces `canUndo`/`canRedo` and reports any
 * failure the replay itself hits.
 *
 * The Content/Layout toggle switches whether `SlideCanvas`/
 * `ElementInspector` show the selected slide's own content or its named
 * layout's zones (`plan.slideLayouts`/`plan.layoutSlide`) -- disabled
 * with an inline reason on the furniture pseudo-slide (no layout of its
 * own) or a freeform slide (`layout: null`, nothing to edit). Toggling
 * to Layout view fetches that layout's zones on demand
 * (`plan.loadLayoutZones`) rather than eagerly for every slide, since
 * most editing sessions never touch it.
 */
import { useEffect, useState } from "react";
import { useAppContext } from "../state/AppContext";
import { FURNITURE_SLIDE_ID, type UsePlanResult } from "../state/usePlan";

const ZOOM_STEPS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3];

interface Props {
  plan: UsePlanResult;
}

export default function Toolbar({ plan }: Props) {
  const { state, dispatch } = useAppContext();
  const [error, setError] = useState<string | null>(null);

  const isFurnitureSelected = state.selectedSlideId === FURNITURE_SLIDE_ID;
  const layoutName = state.selectedSlideId
    ? (plan.slideLayouts[state.selectedSlideId] ?? null)
    : null;
  const layoutToggleDisabled = isFurnitureSelected || layoutName === null;

  // Fetch the selected slide's layout zones whenever Layout view is
  // active and the underlying layout name changes (e.g. switching
  // slides while already in Layout view) -- `loadLayoutZones` is a
  // no-op-safe, on-demand fetch, not part of `usePlan`'s eager refetch.
  // Deliberately keyed only on `slideViewMode`/`layoutName`, not `plan`
  // itself -- `usePlan()` returns a fresh object every render, so
  // including it would refetch on every unrelated re-render instead of
  // only when the thing this effect actually cares about changes.
  useEffect(() => {
    if (state.slideViewMode === "layout" && layoutName) {
      void plan.loadLayoutZones(layoutName);
    }
  }, [state.slideViewMode, layoutName]);

  async function handleUndo() {
    try {
      await plan.undo();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleRedo() {
    try {
      await plan.redo();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="toolbar">
      <label>
        Zoom
        <select
          value={state.zoom}
          onChange={(e) => dispatch({ type: "SET_ZOOM", zoom: Number(e.target.value) })}
        >
          {ZOOM_STEPS.map((z) => (
            <option key={z} value={z}>
              {Math.round(z * 100)}%
            </option>
          ))}
        </select>
      </label>
      <button type="button" disabled={!plan.canUndo} onClick={() => void handleUndo()}>
        Undo
      </button>
      <button type="button" disabled={!plan.canRedo} onClick={() => void handleRedo()}>
        Redo
      </button>
      <div className="toolbar__view-toggle" role="group" aria-label="Content or layout view">
        <button
          type="button"
          className={state.slideViewMode === "content" ? "active" : ""}
          onClick={() => dispatch({ type: "SET_SLIDE_VIEW_MODE", mode: "content" })}
        >
          Content
        </button>
        <button
          type="button"
          className={state.slideViewMode === "layout" ? "active" : ""}
          disabled={layoutToggleDisabled}
          title={
            isFurnitureSelected
              ? "The furniture pseudo-slide has no layout of its own"
              : layoutName === null
                ? "This slide has no layout (freeform) -- nothing to edit here"
                : undefined
          }
          onClick={() => dispatch({ type: "SET_SLIDE_VIEW_MODE", mode: "layout" })}
        >
          Layout
        </button>
      </div>
      {state.slideViewMode === "layout" && layoutName && (
        <span className="toolbar__layout-banner" role="status">
          Editing shared layout &ldquo;{layoutName}&rdquo; -- changes apply to every slide using
          it.
        </span>
      )}
      <label className="toolbar__furniture-toggle">
        <input
          type="checkbox"
          checked={state.showFurniture}
          onChange={(e) => dispatch({ type: "SET_SHOW_FURNITURE", show: e.target.checked })}
        />
        Show furniture (background/watermark/branding/page number)
      </label>
      {error && (
        <span className="toolbar__error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
