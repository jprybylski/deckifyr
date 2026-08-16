/**
 * Owns the fetched `/api/plan` slide data and `design.yaml` slide
 * dimensions, plus every element mutation (`PATCH .../elements/{id}`)
 * and the undo/redo *execution* (as opposed to `reducer.ts`, which only
 * tracks which history entries exist -- this hook is what actually
 * replays a `patch`/`inverse` over the network and refetches).
 *
 * Called once from `App.tsx` and threaded down as props, rather than a
 * second context, so `SlideCanvas`/`SlideList`/`Toolbar`/
 * `ElementInspector` all see the same slide list without each firing
 * its own `/api/plan` request.
 */
import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  deleteSlide,
  getConfig,
  getFurniture,
  getLayoutZones,
  getPlan,
  patchElement,
  patchFurnitureElement,
  patchLayoutElement,
  postAddSlide,
} from "../api/client";
import { boxToInches, parseInchesString } from "../geometry";
import type { ElementPatchBody, ResolvedElement, ResolvedSlide } from "../types";
import { useAppContext } from "./AppContext";
import type { HistoryEntry } from "./reducer";

/** The synthetic slide id prefix `usePlan`/`SlideCanvas`/`ElementInspector`
 * use to address a layout's own zones through the same `applyElementPatch`/
 * undo/redo machinery real slides and the furniture pseudo-slide already
 * share (issue #23's Content/Layout tab) -- `sendPatch` below strips the
 * prefix back off to get the real layout name for `patchLayoutElement`. */
const LAYOUT_SLIDE_PREFIX = "__layout__";

/** The synthetic slide id `GET /api/furniture` returns (issue #21) --
 * matches `deckifyr.web.app`'s own `FURNITURE_SLIDE_ID` constant. Not a
 * real `presentation.yaml` slide, so every consumer that keys off
 * `selectedSlideId` needs to special-case it rather than looking it up
 * in `slides`. */
export const FURNITURE_SLIDE_ID = "__furniture__";

export interface DesignSlideSize {
  widthIn: number;
  heightIn: number;
}

/** `design.yaml`'s `slide.width`/`slide.height` (spec section 7.4) --
 * the only place slide pixel dimensions come from; confirmed against
 * `inst/examples/minimal-deck/design.yaml`, which nests them under a
 * top-level `slide:` block as unit strings like `"13.333in"`. */
function readSlideSize(designDoc: Record<string, unknown>): DesignSlideSize {
  const slide = (designDoc.slide ?? {}) as Record<string, unknown>;
  const width = typeof slide.width === "string" ? slide.width : "13.333in";
  const height = typeof slide.height === "string" ? slide.height : "7.5in";
  return { widthIn: parseInchesString(width), heightIn: parseInchesString(height) };
}

/** Routes an element patch to the right endpoint -- `FURNITURE_SLIDE_ID`
 * goes to the furniture routes (`design.yaml`), anything else to the
 * ordinary per-slide element route (`presentation.yaml`) -- so
 * `applyElementPatch`/`undo`/`redo` all work identically for both
 * without the caller (`SlideCanvas`/`ElementInspector`) needing to know
 * which backend a given slide id actually maps to. */
function sendPatch(slideId: string, elementId: string, patch: ElementPatchBody) {
  if (slideId === FURNITURE_SLIDE_ID) return patchFurnitureElement(elementId, patch);
  if (slideId.startsWith(LAYOUT_SLIDE_PREFIX)) {
    return patchLayoutElement(slideId.slice(LAYOUT_SLIDE_PREFIX.length), elementId, patch);
  }
  return patchElement(slideId, elementId, patch);
}

export function findElement(
  slide: ResolvedSlide | undefined,
  elementId: string | null
): ResolvedElement | undefined {
  if (!slide || !elementId) return undefined;
  return slide.elements.find((el) => el.id === elementId);
}

export interface UsePlanResult {
  slides: ResolvedSlide[] | null;
  /** `design.yaml`'s `furniture` block, resolved the same way a real
   * slide's elements are (issue #21) -- kept separate from `slides`
   * rather than prepended into it, so every existing `slides.length`/
   * `slides.map` consumer (slide numbering, Toolbar, ...) is unaffected.
   * `null` while loading, same as `slides`/`slideSize`. */
  furnitureSlide: ResolvedSlide | null;
  /** Each real slide's `layout` name (`null` = freeform), keyed by slide
   * id (issue #23's Content/Layout tab) -- `PlanResponse.slide_layouts`,
   * unchanged shape. */
  slideLayouts: Record<string, string | null>;
  /** The currently-loaded layout's own zones (issue #23), or `null`
   * before `loadLayoutZones` has been called for one -- distinct from
   * `slides`/`furnitureSlide` in that it's fetched on demand (only when
   * Layout view is actually toggled on for a slide), not eagerly on
   * every `refetch`. */
  layoutSlide: ResolvedSlide | null;
  layoutError: string | null;
  loadLayoutZones: (layoutName: string) => Promise<void>;
  slideSize: DesignSlideSize | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
  /** Add/remove a slide (issue #23) -- not part of the undo/redo patch
   * history (structural, not a field edit, same as furniture add/remove
   * today). Both refetch the plan on success. */
  addSlide: (body: {
    id: string;
    layout: string | null;
    index?: number;
    after?: string;
    before?: string;
  }) => Promise<void>;
  removeSlide: (slideId: string) => Promise<void>;
  /** Applies `patch`, recording `inverse` (the affected fields' prior
   * values, computed by the caller) as an undo step. Throws `ApiError`
   * on a 422 rejection -- the caller decides how to surface it (e.g.
   * `ElementInspector` shows it inline), and the file on disk is left
   * untouched by the server either way. */
  applyElementPatch: (
    slideId: string,
    elementId: string,
    patch: ElementPatchBody,
    inverse: ElementPatchBody,
    label: string
  ) => Promise<void>;
  undo: () => Promise<void>;
  redo: () => Promise<void>;
  canUndo: boolean;
  canRedo: boolean;
}

export function usePlan(): UsePlanResult {
  const { state, dispatch } = useAppContext();
  const [slides, setSlides] = useState<ResolvedSlide[] | null>(null);
  const [furnitureSlide, setFurnitureSlide] = useState<ResolvedSlide | null>(null);
  const [slideLayouts, setSlideLayouts] = useState<Record<string, string | null>>({});
  const [layoutSlide, setLayoutSlide] = useState<ResolvedSlide | null>(null);
  const [layoutError, setLayoutError] = useState<string | null>(null);
  const [slideSize, setSlideSize] = useState<DesignSlideSize | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadLayoutZones = useCallback(async (layoutName: string) => {
    try {
      const zones = await getLayoutZones(layoutName);
      setLayoutSlide(zones);
      setLayoutError(null);
    } catch (err) {
      setLayoutSlide(null);
      setLayoutError(err instanceof ApiError ? err.message : String(err));
    }
  }, []);

  const refetch = useCallback(async () => {
    // `Promise.allSettled`, not `Promise.all` -- these three are
    // independently useful and must not take each other down. Real
    // scenario this fixes: `presentation.yaml`'s `status_indicator`
    // pointing at a placement `design.yaml` hasn't configured a style
    // for yet makes `GET /api/plan` (real-slide rendering, deliberately
    // strict) fail -- but `GET /api/furniture` is deliberately lenient
    // about exactly that case (`furniture_lenient=True`, `plan.py`'s own
    // docstring) specifically so the furniture pseudo-slide's own "Add"
    // fix stays reachable. A single `Promise.all` would still fail the
    // whole refetch even though `getFurniture()` itself succeeded,
    // leaving `furnitureSlide` stuck on stale data and the fix
    // unreachable -- exactly the trap this replaces.
    const [planResult, designResult, furnitureResult] = await Promise.allSettled([
      getPlan(),
      getConfig("design"),
      getFurniture(),
    ]);

    if (planResult.status === "fulfilled") {
      setSlides(planResult.value.slides);
      setSlideLayouts(planResult.value.slide_layouts ?? {});
      // Seeds the shared dirty indicator from the working copy's own
      // state -- important on a mid-session browser refresh, where a
      // freshly-mounted `AppContext` would otherwise default back to
      // "clean" even though unsaved edits are still sitting in the
      // server's memory (`reducer.ts`'s own `dirty` field docstring).
      dispatch({ type: "SET_DIRTY", dirty: planResult.value.dirty });
    }
    if (designResult.status === "fulfilled") setSlideSize(readSlideSize(designResult.value));
    if (furnitureResult.status === "fulfilled") setFurnitureSlide(furnitureResult.value);

    const rejected = [planResult, designResult, furnitureResult].find(
      (r): r is PromiseRejectedResult => r.status === "rejected"
    );
    setError(
      rejected
        ? rejected.reason instanceof ApiError
          ? rejected.reason.message
          : String(rejected.reason)
        : null
    );
    setLoading(false);
  }, [dispatch]);

  useEffect(() => {
    refetch();
  }, [refetch]);

  /** `refetch()` covers `slides`/`furnitureSlide`/`slideSize` but not
   * `layoutSlide` (fetched on demand per layout name, not eagerly) --
   * without this, committing a drag on a layout zone would visually
   * "snap back" right after the PATCH resolves, since the canvas is
   * driven by `layoutSlide`'s stale, pre-drag geometry until something
   * else happens to reload it. Only refetches the layout actually
   * touched (`patchedSlideId`'s `__layout__<name>` prefix, matching
   * `sendPatch`'s own routing), and only when one was already loaded --
   * a patch/undo/redo against an ordinary slide or the furniture
   * pseudo-slide leaves `layoutSlide` untouched, same as before. */
  const refetchAfterPatch = useCallback(
    async (patchedSlideId: string) => {
      await refetch();
      if (patchedSlideId.startsWith(LAYOUT_SLIDE_PREFIX) && layoutSlide) {
        await loadLayoutZones(patchedSlideId.slice(LAYOUT_SLIDE_PREFIX.length));
      }
    },
    [refetch, loadLayoutZones, layoutSlide]
  );

  // Default slide selection to the first slide once the plan loads.
  useEffect(() => {
    if (slides && slides.length > 0 && state.selectedSlideId === null) {
      dispatch({ type: "SELECT_SLIDE", slideId: slides[0].id });
    }
  }, [slides, state.selectedSlideId, dispatch]);

  const addSlide = useCallback(
    async (body: {
      id: string;
      layout: string | null;
      index?: number;
      after?: string;
      before?: string;
    }) => {
      await postAddSlide(body);
      await refetch();
    },
    [refetch]
  );

  const removeSlide = useCallback(
    async (slideId: string) => {
      await deleteSlide(slideId);
      await refetch();
    },
    [refetch]
  );

  const applyElementPatch = useCallback(
    async (
      slideId: string,
      elementId: string,
      patch: ElementPatchBody,
      inverse: ElementPatchBody,
      label: string
    ) => {
      await sendPatch(slideId, elementId, patch);
      const entry: HistoryEntry = { slideId, elementId, patch, inverse, label };
      dispatch({ type: "PUSH_HISTORY", entry });
      await refetchAfterPatch(slideId);
    },
    [dispatch, refetchAfterPatch]
  );

  const undo = useCallback(async () => {
    const entry = state.past[state.past.length - 1];
    if (!entry) return;
    await sendPatch(entry.slideId, entry.elementId, entry.inverse);
    dispatch({ type: "UNDO" });
    await refetchAfterPatch(entry.slideId);
  }, [state.past, dispatch, refetchAfterPatch]);

  const redo = useCallback(async () => {
    const entry = state.future[0];
    if (!entry) return;
    await sendPatch(entry.slideId, entry.elementId, entry.patch);
    dispatch({ type: "REDO" });
    await refetchAfterPatch(entry.slideId);
  }, [state.future, dispatch, refetchAfterPatch]);

  return {
    slides,
    furnitureSlide,
    slideLayouts,
    layoutSlide,
    layoutError,
    loadLayoutZones,
    slideSize,
    loading,
    error,
    refetch,
    addSlide,
    removeSlide,
    applyElementPatch,
    undo,
    redo,
    canUndo: state.past.length > 0,
    canRedo: state.future.length > 0,
  };
}

/** Build the `inverse` patch for a box/rotation change from an
 * element's current (pre-edit) resolved state -- shared by every
 * `SlideCanvas`/`ElementInspector` mutation so undo always restores
 * exactly the fields the forward patch touched, nothing more. */
export function inverseForBoxPatch(
  element: ResolvedElement,
  patch: ElementPatchBody
): ElementPatchBody {
  const inverse: ElementPatchBody = {};
  if (patch.box) {
    const current = boxToInches(element.box);
    inverse.box = {};
    for (const key of Object.keys(patch.box) as Array<keyof typeof patch.box>) {
      inverse.box[key] = current[key];
    }
  }
  if (patch.rotation !== undefined) inverse.rotation = element.rotation;
  if (patch.z_index !== undefined) inverse.z_index = element.z_index;
  if (patch.value !== undefined) inverse.value = String(element.value ?? "");
  return inverse;
}
