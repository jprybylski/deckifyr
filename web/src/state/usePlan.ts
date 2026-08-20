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
  addLayoutElement,
  addSlideElement,
  deleteLayout,
  deleteLayoutElement,
  deleteSlide,
  deleteSlideElement,
  duplicateSlide as apiDuplicateSlide,
  getConfig,
  getFurniture,
  getLayouts,
  getPlan,
  patchElement,
  patchFurnitureElement,
  patchLayoutElement,
  postAddLayout,
  postAddSlide,
} from "../api/client";
import { boxToInches, parseInchesString } from "../geometry";
import type { ElementPatchBody, NewElementBody, ResolvedElement, ResolvedSlide } from "../types";
import { useAppContext } from "./AppContext";
import type { HistoryEntry } from "./reducer";

/** The synthetic slide id prefix `usePlan`/`SlideCanvas`/`ElementInspector`
 * use to address a layout's own zones through the same `applyElementPatch`/
 * undo/redo (and, since issue #30, add/remove) machinery real slides and
 * the furniture pseudo-slide already share -- `sendPatch`/`addElement`/
 * `removeElement` below strip the prefix back off to get the real layout
 * name for the `.../layouts/{name}/...` routes. */
export const LAYOUT_SLIDE_PREFIX = "__layout__";

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
   * id -- `PlanResponse.slide_layouts`. Used by `SlideList` (issue #30)
   * to preview which slides a layout removal would reassign to `blank`. */
  slideLayouts: Record<string, string | null>;
  /** Every layout in `layouts.yaml`, resolved the same `ResolvedSlide`
   * shape `slides` already is (`id` is `"__layout__<name>"`) -- fetched
   * eagerly on every `refetch`, the same as `furnitureSlide`, since
   * issue #30's Layouts editor mode needs every layout's own element
   * count up front, not just whichever one happens to be selected. This
   * is what issue #23's original on-demand single-layout fetch
   * (`loadLayoutZones`/`layoutSlide`) has been replaced with -- selecting
   * a layout now works exactly like selecting a slide, just against this
   * array instead of `slides`. */
  layouts: ResolvedSlide[] | null;
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
  /** Copies an existing slide's layout/elements/notes into a new slide
   * placed immediately after it (issue #31 follow-up). */
  duplicateSlide: (slideId: string, newId: string) => Promise<void>;
  /** Add/remove a layout (issue #30) -- same "structural, not part of
   * undo/redo" shape as `addSlide`/`removeSlide`. `removeLayout` throws
   * `ApiError` (422) if the removal was rejected -- either `blank`
   * itself, or a reassignment that would leave a slide unbuildable
   * (`deckifyr.web.app.remove_layout`'s own docstring); the caller
   * decides how to surface that. */
  addLayout: (id: string) => Promise<void>;
  removeLayout: (layoutName: string) => Promise<void>;
  /** Add/remove an element on an ordinary slide or a layout's own zones
   * (issue #31) -- `slideId` may be a real slide id or a `__layout__`-
   * prefixed one, routed the same way `applyElementPatch` already routes
   * a patch (furniture uses its own fixed-cardinality Add/Remove, not
   * this). Both refetch on success; not part of the undo/redo stack. */
  addElement: (slideId: string, body: NewElementBody) => Promise<void>;
  removeElement: (slideId: string, elementId: string) => Promise<void>;
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
  const [layouts, setLayouts] = useState<ResolvedSlide[] | null>(null);
  const [slideSize, setSlideSize] = useState<DesignSlideSize | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    // `Promise.allSettled`, not `Promise.all` -- these four are
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
    // unreachable -- exactly the trap this replaces. `getLayouts()`
    // joins the same batch for the same reason (issue #30): a broken
    // `GET /api/plan` must not also block the Layouts editor mode from
    // being reachable to fix it.
    const [planResult, designResult, furnitureResult, layoutsResult] = await Promise.allSettled([
      getPlan(),
      getConfig("design"),
      getFurniture(),
      getLayouts(),
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
    if (layoutsResult.status === "fulfilled") setLayouts(layoutsResult.value.layouts);

    const rejected = [planResult, designResult, furnitureResult, layoutsResult].find(
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

  // Default slide selection to the first item of whichever collection
  // `editorMode` currently picks, once it loads -- covers both the
  // initial load and switching modes (`SET_EDITOR_MODE` resets
  // `selectedSlideId` back to `null` specifically so this effect
  // repopulates it, `reducer.ts`'s own docstring).
  useEffect(() => {
    const active = state.editorMode === "layouts" ? layouts : slides;
    if (active && active.length > 0 && state.selectedSlideId === null) {
      dispatch({ type: "SELECT_SLIDE", slideId: active[0].id });
    }
  }, [slides, layouts, state.editorMode, state.selectedSlideId, dispatch]);

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

  const duplicateSlide = useCallback(
    async (slideId: string, newId: string) => {
      await apiDuplicateSlide(slideId, newId);
      await refetch();
    },
    [refetch]
  );

  const addLayout = useCallback(
    async (id: string) => {
      await postAddLayout(id);
      await refetch();
    },
    [refetch]
  );

  const removeLayout = useCallback(
    async (layoutName: string) => {
      await deleteLayout(layoutName);
      await refetch();
    },
    [refetch]
  );

  const addElement = useCallback(
    async (slideId: string, body: NewElementBody) => {
      if (slideId.startsWith(LAYOUT_SLIDE_PREFIX)) {
        await addLayoutElement(slideId.slice(LAYOUT_SLIDE_PREFIX.length), body);
      } else {
        await addSlideElement(slideId, body);
      }
      await refetch();
    },
    [refetch]
  );

  const removeElement = useCallback(
    async (slideId: string, elementId: string) => {
      if (slideId.startsWith(LAYOUT_SLIDE_PREFIX)) {
        await deleteLayoutElement(slideId.slice(LAYOUT_SLIDE_PREFIX.length), elementId);
      } else {
        await deleteSlideElement(slideId, elementId);
      }
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
      await refetch();
    },
    [dispatch, refetch]
  );

  const undo = useCallback(async () => {
    const entry = state.past[state.past.length - 1];
    if (!entry) return;
    await sendPatch(entry.slideId, entry.elementId, entry.inverse);
    dispatch({ type: "UNDO" });
    await refetch();
  }, [state.past, dispatch, refetch]);

  const redo = useCallback(async () => {
    const entry = state.future[0];
    if (!entry) return;
    await sendPatch(entry.slideId, entry.elementId, entry.patch);
    dispatch({ type: "REDO" });
    await refetch();
  }, [state.future, dispatch, refetch]);

  return {
    slides,
    furnitureSlide,
    slideLayouts,
    layouts,
    slideSize,
    loading,
    error,
    refetch,
    addSlide,
    removeSlide,
    duplicateSlide,
    addLayout,
    removeLayout,
    addElement,
    removeElement,
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
