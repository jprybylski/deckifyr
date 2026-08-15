/**
 * The single place canvas pixels convert to/from inches, independent of
 * zoom and device-pixel-ratio, and the place Konva's `transformend`
 * event (which reports `scaleX`/`scaleY`, not new width/height) gets
 * converted back to explicit width/height with scale reset to 1.
 *
 * This is a real, documented Konva footgun, not a hypothetical: dragging
 * a `Transformer` handle mutates the shape's `scaleX`/`scaleY`, leaving
 * `width`/`height` at whatever they were before the resize. The
 * `presentation.yaml` schema (spec section 7.3) has no notion of scale
 * at all -- only a box's literal `width`/`height` -- so if a resize is
 * ever sent to the server as `width * scaleX` without also resetting the
 * node's own `scaleX` back to 1, the *next* resize compounds on top of
 * the stale scale and the element silently drifts. Every function here
 * is pure (no Konva/DOM import) so this drift is covered by a plain
 * unit test, not a browser-driven one.
 */

/** CSS pixels per inch at 100% zoom -- an arbitrary but fixed constant
 * (96 is the standard CSS "reference pixel" density), not derived from
 * `window.devicePixelRatio`: the canvas is a logical drawing surface,
 * and Konva/the browser already handle actual device-pixel scaling
 * separately. Keeping this fixed is what makes pixel<->inch conversion
 * independent of both zoom (an explicit factor below) and DPR. */
export const PIXELS_PER_INCH = 96;

/** Convert an inch measurement to canvas pixels at a given zoom level
 * (1 = 100%). Pure multiplication, but centralized so no call site
 * hand-rolls `* PIXELS_PER_INCH * zoom` differently. */
export function inchesToPixels(inches: number, zoom: number): number {
  return inches * PIXELS_PER_INCH * zoom;
}

/** Inverse of `inchesToPixels`. */
export function pixelsToInches(pixels: number, zoom: number): number {
  return pixels / (PIXELS_PER_INCH * zoom);
}

/** Parse a backend-formatted box field (`"1.5000in"`, always inches,
 * always this exact suffix per `app.py`'s `format_length` -- spec
 * section 7.3 keeps EMU/units internal, the frontend only ever sees
 * inches) into a plain number. Throws on anything that isn't a valid
 * `<number>in` string rather than silently returning `NaN`, so a
 * malformed value fails loudly at the boundary instead of drifting a
 * shape off-slide. */
export function parseInchesString(value: string): number {
  const trimmed = value.trim();
  if (!trimmed.endsWith("in")) {
    throw new Error(`expected an inches string like "1.5in", got ${JSON.stringify(value)}`);
  }
  const numeric = Number(trimmed.slice(0, -2));
  if (Number.isNaN(numeric)) {
    throw new Error(`expected an inches string like "1.5in", got ${JSON.stringify(value)}`);
  }
  return numeric;
}

/** Format a plain inch number the way the rest of this app displays it
 * (not necessarily byte-identical to `format_length`'s own precision --
 * the backend re-formats whatever plain number the frontend PATCHes, so
 * this only needs to be a valid, parseable, human-readable round trip). */
export function formatInchesString(inches: number, precision = 4): string {
  return `${inches.toFixed(precision)}in`;
}

export interface BoxInches {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface ElementBoxLike {
  x: string;
  y: string;
  width: string;
  height: string;
}

/** Parse a `ResolvedElement.box` (four unit strings) into plain inch
 * numbers, e.g. for seeding a Konva node's initial geometry. */
export function boxToInches(box: ElementBoxLike): BoxInches {
  return {
    x: parseInchesString(box.x),
    y: parseInchesString(box.y),
    width: parseInchesString(box.width),
    height: parseInchesString(box.height),
  };
}

/** A box in canvas pixels at a given zoom level. */
export interface BoxPixels {
  x: number;
  y: number;
  width: number;
  height: number;
}

export function boxInchesToPixels(box: BoxInches, zoom: number): BoxPixels {
  return {
    x: inchesToPixels(box.x, zoom),
    y: inchesToPixels(box.y, zoom),
    width: inchesToPixels(box.width, zoom),
    height: inchesToPixels(box.height, zoom),
  };
}

export function boxPixelsToInches(box: BoxPixels, zoom: number): BoxInches {
  return {
    x: pixelsToInches(box.x, zoom),
    y: pixelsToInches(box.y, zoom),
    width: pixelsToInches(box.width, zoom),
    height: pixelsToInches(box.height, zoom),
  };
}

/** The subset of a Konva node's transform state relevant after a
 * `dragend`/`transformend` event -- `width`/`height` are the node's
 * pre-resize dimensions (in px, at the stage's current zoom), and
 * `scaleX`/`scaleY` are what the `Transformer` actually mutated. */
export interface KonvaTransformState {
  x: number;
  y: number;
  width: number;
  height: number;
  scaleX: number;
  scaleY: number;
  rotation: number;
}

export interface ResolvedTransform {
  x: number;
  y: number;
  width: number;
  height: number;
  rotation: number;
  /** Always 1 -- included so a caller applying this back onto the Konva
   * node (`node.scaleX(result.scaleX)`) resets it in the same place the
   * width/height fold-in happened, rather than a separate call site
   * that could be forgotten. */
  scaleX: 1;
  scaleY: 1;
}

/** Fold a Konva `Transformer`'s `scaleX`/`scaleY` into canonical
 * width/height and reset scale to 1 -- the fix for the footgun this
 * module exists for. A resize handle dragged to make a shape twice as
 * wide reports `scaleX: 2`, not `width: <doubled>`; calling this
 * immediately in the `transformend` handler (before ever reading
 * `node.width()`/`node.height()` again) is what keeps a second resize
 * from compounding on a stale scale factor. Widths/heights are clamped
 * to a minimum of 1px so a degenerate drag can't produce a
 * zero/negative-size box the schema would reject. */
export function resolveKonvaTransform(state: KonvaTransformState): ResolvedTransform {
  return {
    x: state.x,
    y: state.y,
    width: Math.max(1, state.width * state.scaleX),
    height: Math.max(1, state.height * state.scaleY),
    rotation: state.rotation,
    scaleX: 1,
    scaleY: 1,
  };
}

/** Convenience: resolve a Konva transform (in px, at some zoom) directly
 * to a `BoxInches` + rotation, in one call -- what `SlideCanvas.tsx`'s
 * `transformend` handler actually wants to PATCH to the server. */
export function resolveKonvaTransformToInches(
  state: KonvaTransformState,
  zoom: number
): BoxInches & { rotation: number } {
  const resolved = resolveKonvaTransform(state);
  const inches = boxPixelsToInches(
    { x: resolved.x, y: resolved.y, width: resolved.width, height: resolved.height },
    zoom
  );
  return { ...inches, rotation: resolved.rotation };
}
