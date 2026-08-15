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
import { findElement, inverseForBoxPatch, type UsePlanResult } from "../state/usePlan";

interface Props {
  plan: UsePlanResult;
}

export default function ElementInspector({ plan }: Props) {
  const { state } = useAppContext();
  const { slides } = plan;
  const [error, setError] = useState<string | null>(null);

  const slide = slides?.find((s) => s.id === state.selectedSlideId);
  const element = findElement(slide, state.selectedElementId);

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

  const isPlaceholder = !["text", "markdown", "image"].includes(element.type);
  // Re-bind as plain (non-optional) locals right after the guard above
  // -- TypeScript can't carry narrowing from an outer `if` into a
  // nested function declaration (the closure could, in principle, run
  // after `element`/`slide` changed), so `submitBox`/`bump` close over
  // these instead of the outer possibly-undefined bindings.
  const currentSlide = slide;
  const currentElement = element;

  async function submitBox() {
    const patch = {
      box: {
        x: Number(fields.x),
        y: Number(fields.y),
        width: Number(fields.width),
        height: Number(fields.height),
      },
      rotation: Number(fields.rotation),
    };
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
      {isPlaceholder && (
        <p className="element-inspector__note">
          {element.type} elements aren't draggable on the canvas yet -- edit this element via
          the config editor instead.
        </p>
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
      <label>
        Rotation (deg)
        <input
          value={fields.rotation}
          onChange={(e) => setFields({ ...fields, rotation: e.target.value })}
        />
      </label>
      <button type="button" onClick={() => void submitBox()}>
        Apply
      </button>

      <div className="element-inspector__zindex">
        <span>z-index: {element.z_index}</span>
        <button type="button" onClick={() => void bump(1)}>
          Bring forward
        </button>
        <button type="button" onClick={() => void bump(-1)}>
          Send backward
        </button>
      </div>

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

