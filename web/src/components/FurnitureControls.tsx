/**
 * Add/remove controls for each furniture kind (background/status/
 * branding/page-number, issue #21), rendered above the canvas only when
 * the furniture pseudo-slide is selected (`App.tsx`'s `EditorTab`).
 *
 * `plan.furnitureSlide.elements` tells us which kinds are already
 * *active* (resolved and rendering) -- each active kind's synthesized
 * `__furniture_*` id is present there, the same ids `SlideCanvas.tsx`/
 * `ElementInspector.tsx` already key off. This component's own small
 * `getConfig("presentation")` fetch (mirroring `DeckOptions.tsx`'s own
 * pattern, not threaded through `usePlan`) reads `status_indicator` and
 * the raw `watermark` override text; see `deckifyr.web.app`'s furniture
 * routes for the server-side half of this "enable vs edit" split (spec
 * section 7.8's own "presence of a whole sub-object is the toggle"
 * framing).
 *
 * "Status" is a single row covering both a corner placement and the
 * full-page watermark -- `status_indicator` (spec section 7.8) is a
 * strict single-select between them, `FURNITURE_STATUS_ID` is the one
 * resolved element either way. This used to be two independent rows
 * (issue #24's `FURNITURE_WATERMARK_ID`, additive alongside a corner via
 * a separate `watermark_overlay` flag and a Deck Options checkbox), but
 * that was reverted after dogfeeding found the two-control surface (a
 * checkbox *and* an Add/Remove pair both toggling the same activation
 * state) more confusing than the corner+watermark combination it enabled
 * was worth -- see `deckifyr.plan.FURNITURE_STATUS_ID`'s own docstring
 * for the fuller reasoning. "Add" here now doubles as the quick,
 * one-click way to get *a* status indicator at all: with nothing
 * selected yet, it defaults to the watermark placement (the same
 * default `deckifyr.web.app.add_furniture_element` picks) rather than
 * requiring the Deck Options dropdown to be touched first; picking a
 * corner instead is still one dropdown change away. "Remove" always
 * clears `status_indicator` back to `None` (not just the style) --
 * `status_indicator: none` is already reachable directly from that same
 * dropdown, so a Remove that left it dangling at a placement with no
 * style would just be a second, worse way to reach the same "nothing
 * configured" state the dropdown already offers cleanly.
 */
import { useEffect, useState } from "react";
import { ApiError, addFurnitureElement, getConfig, removeFurnitureElement } from "../api/client";
import { useAppContext } from "../state/AppContext";
import type { UsePlanResult } from "../state/usePlan";

interface Props {
  plan: UsePlanResult;
  // Called after an add/remove that changes `status_indicator` server-
  // side (`FURNITURE_STATUS_ID` only -- background/branding/page-number
  // never touch it) -- lets `App.tsx`'s `EditorTab` refresh the
  // independently-fetched `DeckOptions` dropdown, which has no other way
  // to learn its own `status_indicator` copy just went stale.
  onStatusIndicatorChanged?: () => void;
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
 * item's style from design.yaml. Shown only while the active placement
 * is the full-page watermark: it's the one furniture kind large enough
 * to visually bury branding/page-number underneath it while positioning
 * them, and the only kind that sits *on top* of ordinary content by
 * design (`z_index: 9999`, spec section 7.8) -- a corner placement is
 * small and behind content like everything else, so it never needs
 * this. */
function StatusHideToggle() {
  const { state, dispatch } = useAppContext();
  const hidden = state.hiddenFurnitureIds.includes(FURNITURE_STATUS_ID);
  return (
    <button
      type="button"
      onClick={() =>
        dispatch({ type: "TOGGLE_FURNITURE_HIDDEN", elementId: FURNITURE_STATUS_ID })
      }
    >
      {hidden ? "Show" : "Hide"}
    </button>
  );
}

export default function FurnitureControls({ plan, onStatusIndicatorChanged }: Props) {
  const [statusIndicator, setStatusIndicator] = useState<string | null>(null);
  // Deck status alone -- what a corner status indicator always shows
  // (`resolve_watermark_text` never applies the watermark override to
  // it). Used for the Status row's own preview text while a corner is
  // (or would be) the active placement.
  const [deckStatusText, setDeckStatusText] = useState<string | null>(null);
  // `watermark` override ?? deck status -- what the watermark placement
  // specifically shows (`resolve_watermark_text`'s own fallback). Used
  // for the Status row's preview text while the watermark is (or would
  // default to being) the active placement.
  const [watermarkResolvedText, setWatermarkResolvedText] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getConfig("presentation")
      .then((data) => {
        if (cancelled) return;
        const indicator = typeof data.status_indicator === "string" ? data.status_indicator : null;
        setStatusIndicator(indicator);
        const metadata = data.metadata as Record<string, unknown> | undefined;
        const watermarkOverride =
          typeof data.watermark === "string" && data.watermark !== "" ? data.watermark : null;
        const deckStatus = typeof metadata?.status === "string" ? metadata.status : null;
        setDeckStatusText(deckStatus);
        setWatermarkResolvedText(watermarkOverride ?? deckStatus);
      })
      .catch(() => {
        // Non-fatal -- the Status row just falls back to its own "add"
        // state, same as if nothing were set.
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
  const statusActive = presentIds.has(FURNITURE_STATUS_ID);
  // "Add" with nothing selected yet defaults to the watermark placement
  // (mirrors `add_furniture_element`'s own default) -- so the preview
  // text before adding is the watermark's, unless a corner is already
  // the chosen (if not yet materialized) placement.
  const previewIsWatermark = statusIndicator === null || statusIndicator === "none" || statusIndicator === "watermark";
  const previewText = previewIsWatermark ? watermarkResolvedText : deckStatusText;

  async function add(elementId: string) {
    setBusyId(elementId);
    setError(null);
    try {
      await addFurnitureElement(elementId);
      await plan.refetch();
      if (elementId === FURNITURE_STATUS_ID) onStatusIndicatorChanged?.();
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
      if (elementId === FURNITURE_STATUS_ID) onStatusIndicatorChanged?.();
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
        Status
        {statusActive ? (
          <>
            {statusIndicator === "watermark" && <StatusHideToggle />}
            <button
              type="button"
              disabled={busyId === FURNITURE_STATUS_ID}
              onClick={() => void remove(FURNITURE_STATUS_ID)}
            >
              Remove
            </button>
            <span className="furniture-controls__hint">
              configured{previewText && ` ("${previewText}")`}
            </span>
          </>
        ) : (
          <>
            <button
              type="button"
              disabled={busyId === FURNITURE_STATUS_ID || !previewText}
              onClick={() => void add(FURNITURE_STATUS_ID)}
            >
              Add
            </button>
            <span className="furniture-controls__hint">
              {previewText
                ? `will show "${previewText}"`
                : "set Deck status above first -- nothing to show yet"}
            </span>
          </>
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
