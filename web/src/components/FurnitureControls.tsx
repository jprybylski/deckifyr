/**
 * Add/remove controls for each furniture kind (background/status/
 * branding/page-number, issue #21), rendered above the canvas only when
 * the furniture pseudo-slide is selected (`App.tsx`'s `EditorTab`).
 *
 * `plan.furnitureSlide.elements` tells us which kinds are already
 * configured -- each configured kind's synthesized `__furniture_*` id is
 * present there, the same ids `SlideCanvas.tsx`/`ElementInspector.tsx`
 * already key off. This component's own small `getConfig("presentation")`
 * fetch (mirroring `DeckOptions.tsx`'s own pattern, not threaded through
 * `usePlan`) is only for reading `status_indicator` -- "add status"
 * needs to know which placement (`corner-tr`, `watermark`, ...) is
 * currently selected there before it can materialize a default style
 * for the right one; see `deckifyr.web.app`'s furniture routes for the
 * server-side half of this "enable vs edit" split (spec section 7.8's
 * own "presence of a whole sub-object is the toggle" framing).
 */
import { useEffect, useState } from "react";
import { ApiError, addFurnitureElement, getConfig, removeFurnitureElement } from "../api/client";
import { useAppContext } from "../state/AppContext";
import type { UsePlanResult } from "../state/usePlan";

interface Props {
  plan: UsePlanResult;
}

// Mirrors `inst/python/deckifyr/plan.py`'s public `FURNITURE_*_ID`
// constants -- kept as plain literals here rather than imported, since
// there's no shared TS module for them yet (only `SlideCanvas.tsx`'s
// `FURNITURE_PREFIX`/predicate helpers are exported today).
const FURNITURE_BACKGROUND_ID = "__furniture_background";
const FURNITURE_STATUS_ID = "__furniture_status";
const FURNITURE_BRANDING_ID = "__furniture_branding";
const FURNITURE_PAGE_NUMBER_ID = "__furniture_page_number";

/** Client-only Hide/Show toggle (`state.hiddenFurnitureIds`,
 * `reducer.ts`) -- distinct from `remove` below, which deletes the
 * item's style from design.yaml. Scoped to the full-page `watermark`
 * placement only: it's the one furniture kind large enough to visually
 * bury branding/page-number underneath it while positioning them, and
 * it's the only kind that sits *on top* of ordinary content by design
 * (`z_index: 9999`, spec section 7.8) -- a corner placement is small and
 * behind content like everything else, and background sits furthest
 * *behind* everything (`z_index: -1000`), so neither one obscures
 * anything a Hide toggle would help with. Not offered at all unless
 * `statusIndicator === "watermark"` is actually the active placement. */
function WatermarkHideToggle() {
  const { state, dispatch } = useAppContext();
  const hidden = state.hiddenFurnitureIds.includes(FURNITURE_STATUS_ID);
  return (
    <button
      type="button"
      onClick={() => dispatch({ type: "TOGGLE_FURNITURE_HIDDEN", elementId: FURNITURE_STATUS_ID })}
    >
      {hidden ? "Show" : "Hide"}
    </button>
  );
}

export default function FurnitureControls({ plan }: Props) {
  const [statusIndicator, setStatusIndicator] = useState<string | null>(null);
  // Resolved the same way `deckifyr.plan.resolve_watermark_text` does
  // server-side (`watermark ?? metadata.status`) -- so "Add" can show
  // *what text will actually appear* before the user commits to it, not
  // just a bare "Add" button. A real user couldn't tell what "test"
  // (typed into the old override-only field) would actually produce
  // until after adding it and hunting for it on the canvas.
  const [resolvedStatusText, setResolvedStatusText] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getConfig("presentation")
      .then((data) => {
        if (cancelled) return;
        setStatusIndicator(typeof data.status_indicator === "string" ? data.status_indicator : null);
        const metadata = data.metadata as Record<string, unknown> | undefined;
        const watermarkOverride = typeof data.watermark === "string" ? data.watermark : null;
        const deckStatus = typeof metadata?.status === "string" ? metadata.status : null;
        setResolvedStatusText(watermarkOverride ?? deckStatus);
      })
      .catch(() => {
        // Non-fatal -- the "status" row just falls back to its own
        // "choose a placement first" state, same as if none were set.
      });
    return () => {
      cancelled = true;
    };
    // Re-read after every furniture refetch, since `DeckOptions` (a
    // sibling, independent fetch/save of the same `presentation.yaml`
    // fields) may have changed `status_indicator`/`watermark`/
    // `metadata.status` since this last ran.
  }, [plan.furnitureSlide]);

  const presentIds = new Set((plan.furnitureSlide?.elements ?? []).map((el) => el.id));
  const hasStatusPlacement = statusIndicator !== null && statusIndicator !== "none";

  async function add(elementId: string) {
    setBusyId(elementId);
    setError(null);
    try {
      await addFurnitureElement(elementId);
      await plan.refetch();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  async function remove(elementId: string) {
    setBusyId(elementId);
    setError(null);
    try {
      await removeFurnitureElement(elementId);
      await plan.refetch();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="furniture-controls">
      <span className="furniture-controls__label">Furniture:</span>

      <span className="furniture-controls__item">
        Background
        <span className="furniture-controls__hint">
          {presentIds.has(FURNITURE_BACKGROUND_ID) ? "set" : "not set"} -- edit via Config tab
        </span>
      </span>

      <span className="furniture-controls__item">
        Status/watermark
        {presentIds.has(FURNITURE_STATUS_ID) ? (
          <>
            {statusIndicator === "watermark" && <WatermarkHideToggle />}
            {/* No Remove button here on purpose: this always targets
                whichever placement presentation.yaml's status_indicator
                currently points at, so removing it while that's still
                selected breaks the plan for every slide (not just this
                pseudo-slide) with a "furniture.status has no X configured"
                error -- confirmed the hard way against a real project. The
                deck-wide "Status/watermark" dropdown above is the safe way
                to turn this off; it doesn't touch design.yaml at all. */}
            <span className="furniture-controls__hint">
              configured{resolvedStatusText && ` ("${resolvedStatusText}")`} -- set Status/watermark to
              None above to turn it off
            </span>
          </>
        ) : hasStatusPlacement ? (
          <>
            <button
              type="button"
              disabled={busyId === FURNITURE_STATUS_ID || !resolvedStatusText}
              onClick={() => void add(FURNITURE_STATUS_ID)}
            >
              Add
            </button>
            <span className="furniture-controls__hint">
              {resolvedStatusText
                ? `will show "${resolvedStatusText}"`
                : "set Deck status above first -- nothing to show yet"}
            </span>
          </>
        ) : (
          <span className="furniture-controls__hint">choose a placement in Deck Options first</span>
        )}
      </span>

      <span className="furniture-controls__item">
        Branding
        {presentIds.has(FURNITURE_BRANDING_ID) ? (
          <button
            type="button"
            disabled={busyId === FURNITURE_BRANDING_ID}
            onClick={() => void remove(FURNITURE_BRANDING_ID)}
          >
            Remove
          </button>
        ) : (
          <button
            type="button"
            disabled={busyId === FURNITURE_BRANDING_ID}
            onClick={() => void add(FURNITURE_BRANDING_ID)}
          >
            Add
          </button>
        )}
      </span>

      <span className="furniture-controls__item">
        Page number
        {presentIds.has(FURNITURE_PAGE_NUMBER_ID) ? (
          <button
            type="button"
            disabled={busyId === FURNITURE_PAGE_NUMBER_ID}
            onClick={() => void remove(FURNITURE_PAGE_NUMBER_ID)}
          >
            Remove
          </button>
        ) : (
          <button
            type="button"
            disabled={busyId === FURNITURE_PAGE_NUMBER_ID}
            onClick={() => void add(FURNITURE_PAGE_NUMBER_ID)}
          >
            Add
          </button>
        )}
      </span>

      {error && (
        <span className="furniture-controls__error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
