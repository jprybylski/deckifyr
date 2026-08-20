/** Zoom control + undo/redo + a banner naming the shared layout being
 * edited, when applicable. Undo/redo delegate to `usePlan`'s `undo`/
 * `redo` (which replay a `HistoryEntry`'s `inverse`/`patch` over the
 * network and refetch) -- this component only surfaces `canUndo`/
 * `canRedo` and reports any failure the replay itself hits.
 *
 * The Content/Layout toggle this component used to own (issue #23) is
 * gone -- issue #30 replaced it with `SlideList`'s persistent Slides/
 * Layouts mode toggle (`state.editorMode`), which swaps the entire slide
 * list rather than re-targeting the currently-selected one. What's left
 * here is just the "you're editing a shared layout, not one slide"
 * reminder, now derived from `editorMode` + the selected `__layout__`
 * id instead of a per-slide lookup.
 */
import { useState } from "react";
import { useAppContext } from "../state/AppContext";
import { LAYOUT_SLIDE_PREFIX, type UsePlanResult } from "../state/usePlan";

const ZOOM_STEPS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3];

interface Props {
  plan: UsePlanResult;
}

export default function Toolbar({ plan }: Props) {
  const { state, dispatch } = useAppContext();
  const [error, setError] = useState<string | null>(null);

  const layoutName =
    state.editorMode === "layouts" && state.selectedSlideId?.startsWith(LAYOUT_SLIDE_PREFIX)
      ? state.selectedSlideId.slice(LAYOUT_SLIDE_PREFIX.length)
      : null;

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
      {layoutName && (
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
