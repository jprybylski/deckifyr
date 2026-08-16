/**
 * Add/remove controls for each furniture kind (background/status/
 * watermark/branding/page-number, issue #21), rendered above the canvas
 * only when the furniture pseudo-slide is selected (`App.tsx`'s
 * `EditorTab`).
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
 * "Watermark" and "Status" are two fully independent rows -- not a UI
 * convenience, but a real reflection of the underlying schema:
 * `FURNITURE_WATERMARK_ID` (`__furniture_watermark`) and
 * `FURNITURE_STATUS_ID` (`__furniture_status`) are two separate resolved
 * elements that can both be present in `plan.furnitureSlide.elements` at
 * once (`deckifyr.plan.FURNITURE_WATERMARK_ID`'s own docstring) --
 * `status_indicator` (corner-or-watermark single-select, unchanged) only
 * ever controls Status; the watermark is active whenever *either*
 * `status_indicator === "watermark"` or the separate, additive
 * `watermark_overlay` flag is true, so a watermark and a corner can
 * render simultaneously (the actual reported requirement).
 *
 * The exact rule for when Watermark is "an entity" at all (worth showing
 * Add/Remove for), stated directly and repeatedly by a real user after
 * earlier attempts kept missing it: it's an entity if and only if it's
 * currently active/rendering (`presentIds.has(FURNITURE_WATERMARK_ID)`,
 * server truth), OR override text has actually been typed into
 * "Watermark override" in Deck Options. **Nothing else counts** --
 * `design.yaml` may already have a leftover `furniture.status.watermark`
 * style sitting there from before this session (a real, previously-
 * built-in demo project does), but that fact must never surface a
 * "Remove" button or otherwise influence this row; a real regression in
 * an earlier version consulted that raw design.yaml state directly and
 * it made "Remove" show unconditionally, which then made every other
 * action (typing override text, toggling the overlay) look like it did
 * nothing, since the row was already stuck on "Remove" before any of it.
 * `add()` swallows an "already configured" 422 specifically for the
 * watermark for the same reason: a stale pre-existing style must not
 * block activating it, and must not surface as an error either.
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
const FURNITURE_WATERMARK_ID = "__furniture_watermark";
const FURNITURE_BRANDING_ID = "__furniture_branding";
const FURNITURE_PAGE_NUMBER_ID = "__furniture_page_number";

/** Client-only Hide/Show toggle (`state.hiddenFurnitureIds`,
 * `reducer.ts`) -- distinct from `remove` below, which deletes the
 * item's style from design.yaml. Scoped to the watermark: it's the one
 * furniture kind large enough to visually bury branding/page-number
 * underneath it while positioning them, and it's the only kind that
 * sits *on top* of ordinary content by design (`z_index: 9999`, spec
 * section 7.8) -- a corner placement is small and behind content like
 * everything else, and background sits furthest *behind* everything
 * (`z_index: -1000`), so neither one obscures anything a Hide toggle
 * would help with. */
function WatermarkHideToggle() {
  const { state, dispatch } = useAppContext();
  const hidden = state.hiddenFurnitureIds.includes(FURNITURE_WATERMARK_ID);
  return (
    <button
      type="button"
      onClick={() =>
        dispatch({ type: "TOGGLE_FURNITURE_HIDDEN", elementId: FURNITURE_WATERMARK_ID })
      }
    >
      {hidden ? "Show" : "Hide"}
    </button>
  );
}

export default function FurnitureControls({ plan }: Props) {
  const [statusIndicator, setStatusIndicator] = useState<string | null>(null);
  // Deck status alone -- what the corner status indicator always shows
  // (`resolve_watermark_text` never applies the watermark override to
  // it). Used for the Status row's own preview text.
  const [deckStatusText, setDeckStatusText] = useState<string | null>(null);
  // The literal `presentation.watermark` field value, un-resolved (no
  // Deck-status fallback) -- specifically what determines whether
  // Watermark is "an entity" while inactive (see this module's own
  // docstring for the exact rule). Deck status alone does *not* count
  // on its own here, even though it's a valid fallback once the
  // watermark actually is active -- a project's Deck status is almost
  // always set to something, so treating it as "the user configured a
  // watermark" would make nearly every session show a spurious
  // Watermark entity.
  const [watermarkOverrideRaw, setWatermarkOverrideRaw] = useState<string | null>(null);
  // `watermarkOverrideRaw ?? deckStatus` -- what the watermark actually
  // shows once active (`resolve_watermark_text`'s own fallback,
  // unconditional now that the watermark is its own element).
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
        setWatermarkOverrideRaw(watermarkOverride);
        setWatermarkResolvedText(watermarkOverride ?? deckStatus);
      })
      .catch(() => {
        // Non-fatal -- the Watermark/Status rows just fall back to their
        // own "choose a placement first" state, same as if none were set.
      });
    return () => {
      cancelled = true;
    };
    // Re-read after every furniture refetch, since `DeckOptions` (a
    // sibling, independent fetch/save of the same `presentation.yaml`
    // fields) may have changed `status_indicator`/`watermark_overlay`/
    // `watermark`/`metadata.status` since this last ran.
  }, [plan.furnitureSlide]);

  const presentIds = new Set((plan.furnitureSlide?.elements ?? []).map((el) => el.id));
  const isCornerMode = statusIndicator !== null && statusIndicator !== "none";
  const watermarkActive = presentIds.has(FURNITURE_WATERMARK_ID);
  const watermarkIsEntity = watermarkActive || watermarkOverrideRaw !== null;

  async function add(elementId: string) {
    setBusyId(elementId);
    setError(null);
    try {
      await addFurnitureElement(elementId);
      await plan.refetch();
    } catch (err) {
      // A stale style already sitting in design.yaml from before this
      // session (unrelated to anything the user just did) must not
      // block activating the watermark, and must not surface as an
      // error either -- see this module's own docstring.
      if (elementId === FURNITURE_WATERMARK_ID && err instanceof ApiError && err.status === 422) {
        await plan.refetch();
        return;
      }
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
        Watermark
        {!watermarkIsEntity ? (
          <span className="furniture-controls__hint">
            select Watermark in Deck Options, or enter a Watermark override above, to configure
          </span>
        ) : watermarkActive ? (
          <>
            <WatermarkHideToggle />
            <button
              type="button"
              disabled={busyId === FURNITURE_WATERMARK_ID}
              onClick={() => void remove(FURNITURE_WATERMARK_ID)}
            >
              Remove
            </button>
            <span className="furniture-controls__hint">
              configured{watermarkResolvedText && ` ("${watermarkResolvedText}")`}
            </span>
          </>
        ) : (
          <>
            <button
              type="button"
              disabled={busyId === FURNITURE_WATERMARK_ID}
              onClick={() => void add(FURNITURE_WATERMARK_ID)}
            >
              Add
            </button>
            <span className="furniture-controls__hint">
              will show &quot;{watermarkOverrideRaw}&quot;
            </span>
          </>
        )}
      </span>

      <span className="furniture-controls__item">
        Status
        {isCornerMode && presentIds.has(FURNITURE_STATUS_ID) ? (
          <>
            <button
              type="button"
              disabled={busyId === FURNITURE_STATUS_ID}
              onClick={() => void remove(FURNITURE_STATUS_ID)}
            >
              Remove
            </button>
            <span className="furniture-controls__hint">
              configured{deckStatusText && ` ("${deckStatusText}")`}
            </span>
          </>
        ) : isCornerMode ? (
          <>
            <button
              type="button"
              disabled={busyId === FURNITURE_STATUS_ID || !deckStatusText}
              onClick={() => void add(FURNITURE_STATUS_ID)}
            >
              Add
            </button>
            <span className="furniture-controls__hint">
              {deckStatusText
                ? `will show "${deckStatusText}"`
                : "set Deck status above first -- nothing to show yet"}
            </span>
          </>
        ) : (
          <span className="furniture-controls__hint">
            select a corner placement in Deck Options to configure
          </span>
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
