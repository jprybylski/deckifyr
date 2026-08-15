import { describe, expect, it } from "vitest";
import {
  PIXELS_PER_INCH,
  boxInchesToPixels,
  boxPixelsToInches,
  boxToInches,
  formatInchesString,
  inchesToPixels,
  parseInchesString,
  pixelsToInches,
  resolveKonvaTransform,
  resolveKonvaTransformToInches,
} from "./geometry";

describe("inches <-> pixels", () => {
  it("converts at 100% zoom using the fixed PIXELS_PER_INCH constant", () => {
    expect(inchesToPixels(1, 1)).toBe(PIXELS_PER_INCH);
    expect(pixelsToInches(PIXELS_PER_INCH, 1)).toBe(1);
  });

  it("scales with zoom without changing the underlying inch value", () => {
    const oneInchAt200Percent = inchesToPixels(1, 2);
    expect(oneInchAt200Percent).toBe(PIXELS_PER_INCH * 2);
    // Converting back at the same zoom recovers the original inches --
    // the whole point of zoom-independence: the inch value never
    // silently drifts just because the on-screen zoom changed.
    expect(pixelsToInches(oneInchAt200Percent, 2)).toBeCloseTo(1);
  });

  it("round-trips arbitrary values across a range of zoom levels", () => {
    for (const zoom of [0.25, 0.5, 1, 1.5, 3]) {
      const inches = 4.125;
      const px = inchesToPixels(inches, zoom);
      expect(pixelsToInches(px, zoom)).toBeCloseTo(inches);
    }
  });
});

describe("parseInchesString / formatInchesString", () => {
  it("parses a backend-formatted box field", () => {
    expect(parseInchesString("1.5000in")).toBeCloseTo(1.5);
    expect(parseInchesString("0in")).toBe(0);
  });

  it("throws on a value with no trailing unit", () => {
    expect(() => parseInchesString("1.5")).toThrow();
  });

  it("throws on a non-numeric value", () => {
    expect(() => parseInchesString("abcin")).toThrow();
  });

  it("formats back into a parseable inches string", () => {
    const formatted = formatInchesString(2.5);
    expect(formatted.endsWith("in")).toBe(true);
    expect(parseInchesString(formatted)).toBeCloseTo(2.5);
  });
});

describe("boxToInches / boxInchesToPixels / boxPixelsToInches", () => {
  it("parses a full ElementBox and converts it through pixels and back", () => {
    const box = { x: "1.0000in", y: "2.0000in", width: "3.0000in", height: "4.0000in" };
    const inches = boxToInches(box);
    expect(inches).toEqual({ x: 1, y: 2, width: 3, height: 4 });

    const px = boxInchesToPixels(inches, 1.5);
    expect(px.width).toBeCloseTo(3 * PIXELS_PER_INCH * 1.5);

    const back = boxPixelsToInches(px, 1.5);
    expect(back.x).toBeCloseTo(1);
    expect(back.width).toBeCloseTo(3);
  });
});

describe("resolveKonvaTransform (the scaleX/scaleY footgun fix)", () => {
  it("folds scaleX/scaleY into width/height and resets scale to 1", () => {
    const result = resolveKonvaTransform({
      x: 10,
      y: 20,
      width: 100,
      height: 50,
      scaleX: 2,
      scaleY: 1.5,
      rotation: 0,
    });
    expect(result.width).toBe(200);
    expect(result.height).toBe(75);
    expect(result.scaleX).toBe(1);
    expect(result.scaleY).toBe(1);
  });

  it("does not compound scale across two successive transforms", () => {
    // Simulates two resizes in a row: after the first, the caller is
    // expected to have reset the Konva node's own scaleX/scaleY to 1
    // (using this function's output) before the second transform event
    // fires. If that reset is skipped, the second resize's scaleX would
    // multiply against the *already-scaled* width instead of the
    // canonical one -- this test pins the correct (non-compounding)
    // behavior.
    const first = resolveKonvaTransform({
      x: 0,
      y: 0,
      width: 100,
      height: 100,
      scaleX: 2,
      scaleY: 2,
      rotation: 0,
    });
    expect(first.width).toBe(200);

    // Second transform starts from the *resolved* width/height (as it
    // would in the real component, since the node's own width/height
    // prop is updated from `first.width`/`first.height` and scale reset
    // to `first.scaleX`/`first.scaleY`, i.e. 1) with a fresh scale
    // factor of 1.5.
    const second = resolveKonvaTransform({
      x: 0,
      y: 0,
      width: first.width,
      height: first.height,
      scaleX: 1.5,
      scaleY: 1.5,
      rotation: 0,
    });
    expect(second.width).toBe(300); // 200 * 1.5, not 100 * 2 * 1.5 * ...
  });

  it("clamps degenerate (zero or negative) resizes to a minimum of 1px", () => {
    const result = resolveKonvaTransform({
      x: 0,
      y: 0,
      width: 100,
      height: 100,
      scaleX: 0,
      scaleY: -1,
      rotation: 0,
    });
    expect(result.width).toBe(1);
    expect(result.height).toBe(1);
  });

  it("preserves rotation and position untouched", () => {
    const result = resolveKonvaTransform({
      x: 42,
      y: 7,
      width: 100,
      height: 100,
      scaleX: 1,
      scaleY: 1,
      rotation: 45,
    });
    expect(result.x).toBe(42);
    expect(result.y).toBe(7);
    expect(result.rotation).toBe(45);
  });
});

describe("resolveKonvaTransformToInches", () => {
  it("is zoom-independent: the same on-screen transform yields the same inches regardless of zoom", () => {
    const stateAtZoom = (zoom: number) => ({
      x: inchesToPixels(1, zoom),
      y: inchesToPixels(1, zoom),
      width: inchesToPixels(2, zoom),
      height: inchesToPixels(2, zoom),
      scaleX: 1.5,
      scaleY: 1.5,
      rotation: 30,
    });

    const at1x = resolveKonvaTransformToInches(stateAtZoom(1), 1);
    const at2x = resolveKonvaTransformToInches(stateAtZoom(2), 2);

    expect(at1x.x).toBeCloseTo(at2x.x);
    expect(at1x.y).toBeCloseTo(at2x.y);
    expect(at1x.width).toBeCloseTo(at2x.width);
    expect(at1x.height).toBeCloseTo(at2x.height);
    expect(at1x.width).toBeCloseTo(3); // 2in * scaleX 1.5
    expect(at1x.rotation).toBe(30);
  });
});
