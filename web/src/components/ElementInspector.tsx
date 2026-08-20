/**
 * Numeric-field editor for the selected element's box/rotation/z-index
 * -- the keyboard-driven counterpart to dragging/resizing on
 * `SlideCanvas`. Also where z-index reordering happens (a "bring
 * forward"/"send backward" pair of buttons, since a raw z-index number
 * is otherwise meaningless to a user without seeing every other
 * element's own z-index).
 */
import { useEffect, useState } from "react";
import { useAppContext } from "../state/AppContext";
import { boxToInches, formatInchesString } from "../geometry";
import {
  LAYOUT_SLIDE_PREFIX,
  findElement,
  inverseForBoxPatch,
  type UsePlanResult,
} from "../state/usePlan";
import {
  furnitureElementSupportsRotation,
  furnitureElementSupportsValue,
  furnitureElementSupportsZIndex,
} from "./SlideCanvas";

interface Props {
  plan: UsePlanResult;
}

export default function ElementInspector({ plan }: Props) {
  const { state } = useAppContext();
  const { slides, furnitureSlide } = plan;

  const isFurnitureSlideSelected =
    furnitureSlide !== null && state.selectedSlideId === furnitureSlide.id;
  // Mirrors `SlideCanvas.tsx`'s own `slide` derivation (issue #30): which
  // collection `state.selectedSlideId` is looked up in follows the same
  // persistent `state.editorMode`, not a per-slide toggle.
  const isLayoutsMode = !isFurnitureSlideSelected && state.editorMode === "layouts";
  const slide = isFurnitureSlideSelected
    ? furnitureSlide
    : isLayoutsMode
      ? plan.layouts?.find((l) => l.id === state.selectedSlideId)
      : slides?.find((s) => s.id === state.selectedSlideId);
  const element = findElement(slide, state.selectedElementId);
  const [error, setError] = useState<string | null>(null);

  // Local editable copies of the numeric fields, reset whenever the
  // selected element (or its server-side value) changes -- otherwise a
  // stale input value could linger after an undo/redo or a drag commit.
  const [fields, setFields] = useState({ x: "", y: "", width: "", height: "", rotation: "", z_index: "" });

  useEffect(() => {
    if (!element) return;
    const box = boxToInches(element.box);
    setFields({
      x: box.x.toFixed(4),
      y: box.y.toFixed(4),
      width: box.width.toFixed(4),
      height: box.height.toFixed(4),
      rotation: String(element.rotation),
      z_index: String(element.z_index),
    });
  }, [element]);

  if (!element || !slide) {
    return (
      <aside className="element-inspector">
        <p className="element-inspector__empty">No element selected.</p>
      </aside>
    );
  }

  // `__furniture_*` ids (background/status/branding/page number, spec
  // section 7.8) are synthesized once per slide at plan-time from
  // design.yaml's `furniture` block. On an ordinary real slide there's
  // no `PATCH .../elements/{id}` target for one no matter its `type`,
  // so this note takes priority over the ordinary "not draggable yet"
  // copy below (which implies future per-slide support that will never
  // apply here). On the furniture *pseudo*-slide it's the opposite --
  // these are exactly what's editable there, through `design.yaml`
  // instead of this slide's own elements (issue #21).
  const isFurniture = element.id.startsWith("__furniture_");
  const isPlaceholder = !["text", "markdown", "image"].includes(element.type);
  const rotationSupported = !isFurnitureSlideSelected || furnitureElementSupportsRotation(element.id);
  const zIndexSupported = !isFurnitureSlideSelected || furnitureElementSupportsZIndex(element.id);
  const valueSupported = !isFurnitureSlideSelected || furnitureElementSupportsValue(element.id);
  // Re-bind as plain (non-optional) locals right after the guard above
  // -- TypeScript can't carry narrowing from an outer `if` into a
  // nested function declaration (the closure could, in principle, run
  // after `element`/`slide` changed), so `submitBox`/`bump` close over
  // these instead of the outer possibly-undefined bindings.
  const currentSlide = slide;
  const currentElement = element;

  async function submitBox() {
    const patch: Parameters<UsePlanResult["applyElementPatch"]>[2] = {
      box: {
        x: Number(fields.x),
        y: Number(fields.y),
        width: Number(fields.width),
        height: Number(fields.height),
      },
    };
    // Branding/page-number furniture have no `rotation` field in
    // design.yaml's schema -- the backend hard-rejects a patch that
    // tries to set one there, so this must not send it (see
    // `SlideCanvas.tsx`'s own `furnitureElementSupportsRotation`).
    if (rotationSupported) {
      patch.rotation = Number(fields.rotation);
    }
    const inverse = inverseForBoxPatch(currentElement, patch);
    try {
      await plan.applyElementPatch(currentSlide.id, currentElement.id, patch, inverse, "edit geometry");
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function bump(delta: number) {
    const patch = { z_index: currentElement.z_index + delta };
    const inverse = inverseForBoxPatch(currentElement, patch);
    try {
      await plan.applyElementPatch(currentSlide.id, currentElement.id, patch, inverse, "reorder");
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <aside className="element-inspector">
      <h3>{element.type}</h3>
      <p className="element-inspector__id">{element.id}</p>
      {isFurniture ? (
        isFurnitureSlideSelected ? (
          <p className="element-inspector__note">
            This is a deck-wide furniture element (design.yaml's <code>furniture</code> block) --
            editing its geometry here writes to <code>design.yaml</code>, not this deck's slides,
            and applies to every slide.
            {!rotationSupported && " This item has no rotation field."}
            {!valueSupported &&
              " Its text isn't stored here and can't be edited on the canvas -- it comes from " +
                "presentation.yaml (status/watermark text, or the page-number format string)."}
          </p>
        ) : (
          <p className="element-inspector__note">
            This is a deck-wide furniture element (design.yaml's <code>furniture</code> block), not
            part of this slide -- it's fixed here. Uncheck &ldquo;Show furniture&rdquo; in the
            toolbar to hide it while editing (view-only, doesn&rsquo;t change the built deck), or
            select the &ldquo;⚙ Furniture&rdquo; entry in the slide list to edit it directly.
          </p>
        )
      ) : isLayoutsMode ? (
        <p className="element-inspector__note">
          This is a zone of layout &ldquo;{slide.id.slice(LAYOUT_SLIDE_PREFIX.length)}&rdquo; (
          <code>layouts.yaml</code>) -- editing its geometry here applies to every slide using
          this layout.
        </p>
      ) : (
        isPlaceholder && (
          <p className="element-inspector__note">
            {element.type} elements aren't draggable on the canvas yet -- edit this element via
            the config editor instead.
          </p>
        )
      )}

      <label>
        X (in)
        <input value={fields.x} onChange={(e) => setFields({ ...fields, x: e.target.value })} />
      </label>
      <label>
        Y (in)
        <input value={fields.y} onChange={(e) => setFields({ ...fields, y: e.target.value })} />
      </label>
      <label>
        Width (in)
        <input
          value={fields.width}
          onChange={(e) => setFields({ ...fields, width: e.target.value })}
        />
      </label>
      <label>
        Height (in)
        <input
          value={fields.height}
          onChange={(e) => setFields({ ...fields, height: e.target.value })}
        />
      </label>
      {rotationSupported && (
        <label>
          Rotation (deg)
          <input
            value={fields.rotation}
            onChange={(e) => setFields({ ...fields, rotation: e.target.value })}
          />
        </label>
      )}
      <button type="button" onClick={() => void submitBox()}>
        Apply
      </button>

      {zIndexSupported && (
        <div className="element-inspector__zindex">
          <span>z-index: {element.z_index}</span>
          <button type="button" onClick={() => void bump(1)}>
            Bring forward
          </button>
          <button type="button" onClick={() => void bump(-1)}>
            Send backward
          </button>
        </div>
      )}

      {element.type !== "image" && (
        <p className="element-inspector__hint">
          Box in YAML terms: {formatInchesString(Number(fields.width || 0))} ×{" "}
          {formatInchesString(Number(fields.height || 0))}
        </p>
      )}

      {error && (
        <p className="element-inspector__error" role="alert">
          {error}
        </p>
      )}
    </aside>
  );
}

