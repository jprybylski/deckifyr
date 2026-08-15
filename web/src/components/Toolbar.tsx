/** Zoom control + undo/redo. Undo/redo delegate to `usePlan`'s
 * `undo`/`redo` (which replay a `HistoryEntry`'s `inverse`/`patch` over
 * the network and refetch) -- this component only surfaces `canUndo`/
 * `canRedo` and reports any failure the replay itself hits. */
import { useState } from "react";
import { useAppContext } from "../state/AppContext";
import type { UsePlanResult } from "../state/usePlan";

const ZOOM_STEPS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3];

interface Props {
  plan: UsePlanResult;
}

export default function Toolbar({ plan }: Props) {
  const { state, dispatch } = useAppContext();
  const [error, setError] = useState<string | null>(null);

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
      {error && (
        <span className="toolbar__error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
