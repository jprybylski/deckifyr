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
import { ApiError, getConfig, getPlan, patchElement } from "../api/client";
import { boxToInches, parseInchesString } from "../geometry";
import type { ElementPatchBody, ResolvedElement, ResolvedSlide } from "../types";
import { useAppContext } from "./AppContext";
import type { HistoryEntry } from "./reducer";

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

export function findElement(
  slide: ResolvedSlide | undefined,
  elementId: string | null
): ResolvedElement | undefined {
  if (!slide || !elementId) return undefined;
  return slide.elements.find((el) => el.id === elementId);
}

export interface UsePlanResult {
  slides: ResolvedSlide[] | null;
  slideSize: DesignSlideSize | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
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
  const [slideSize, setSlideSize] = useState<DesignSlideSize | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    try {
      const [plan, design] = await Promise.all([getPlan(), getConfig("design")]);
      setSlides(plan.slides);
      setSlideSize(readSlideSize(design));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  // Default slide selection to the first slide once the plan loads.
  useEffect(() => {
    if (slides && slides.length > 0 && state.selectedSlideId === null) {
      dispatch({ type: "SELECT_SLIDE", slideId: slides[0].id });
    }
  }, [slides, state.selectedSlideId, dispatch]);

  const applyElementPatch = useCallback(
    async (
      slideId: string,
      elementId: string,
      patch: ElementPatchBody,
      inverse: ElementPatchBody,
      label: string
    ) => {
      await patchElement(slideId, elementId, patch);
      const entry: HistoryEntry = { slideId, elementId, patch, inverse, label };
      dispatch({ type: "PUSH_HISTORY", entry });
      await refetch();
    },
    [dispatch, refetch]
  );

  const undo = useCallback(async () => {
    const entry = state.past[state.past.length - 1];
    if (!entry) return;
    await patchElement(entry.slideId, entry.elementId, entry.inverse);
    dispatch({ type: "UNDO" });
    await refetch();
  }, [state.past, dispatch, refetch]);

  const redo = useCallback(async () => {
    const entry = state.future[0];
    if (!entry) return;
    await patchElement(entry.slideId, entry.elementId, entry.patch);
    dispatch({ type: "REDO" });
    await refetch();
  }, [state.future, dispatch, refetch]);

  return {
    slides,
    slideSize,
    loading,
    error,
    refetch,
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
