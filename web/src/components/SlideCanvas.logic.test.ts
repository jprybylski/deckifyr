import { describe, expect, it } from "vitest";
import {
  applyTextTransform,
  centerToTopLeftPx,
  displayText,
  elementLabel,
  furnitureElementSupportsRotation,
  furnitureElementSupportsValue,
  furnitureElementSupportsZIndex,
  isContentPlaceholderElement,
  isDraggableElement,
  isDraggableFurnitureElement,
  isFurnitureElement,
  konvaTextAlign,
  konvaVerticalAlign,
} from "./SlideCanvas";
import type { ElementType, ResolvedElement } from "../types";

function element(overrides: Partial<ResolvedElement>): ResolvedElement {
  return {
    id: "el",
    type: "text",
    value: null,
    source: null,
    box: { x: "0in", y: "0in", width: "1in", height: "1in" },
    rotation: 0,
    z_index: 0,
    order: 0,
    style: null,
    fit: "shrink",
    overflow: "clip",
    render_mode: "native",
    alt_text: null,
    required: false,
    footer_placement: null,
    shape_kind: null,
    shape_style: null,
    table_style: null,
    center: false,
    align: null,
    children: [],
    ...overrides,
  };
}

describe("isFurnitureElement", () => {
  it("is true for every __furniture_* id regardless of type", () => {
    expect(isFurnitureElement(element({ id: "__furniture_background", type: "image" }))).toBe(
      true
    );
    expect(isFurnitureElement(element({ id: "__furniture_status", type: "text" }))).toBe(true);
    expect(isFurnitureElement(element({ id: "__furniture_branding", type: "text" }))).toBe(true);
    expect(
      isFurnitureElement(element({ id: "__furniture_page_number", type: "text" }))
    ).toBe(true);
  });

  it("is false for an ordinary slide element, even one with a similar-looking id", () => {
    expect(isFurnitureElement(element({ id: "title" }))).toBe(false);
    expect(isFurnitureElement(element({ id: "furniture-but-not-really" }))).toBe(false);
  });
});

describe("isDraggableElement", () => {
  it("is draggable for text/markdown/image/shape/table/reportifyr/quarto elements", () => {
    for (const type of [
      "text",
      "markdown",
      "image",
      "shape",
      "table",
      "reportifyr",
      "quarto",
    ] as const) {
      expect(isDraggableElement(element({ id: "x", type }))).toBe(true);
    }
  });

  it("is never draggable for group elements (issue #55 -- its box is ignored by the compositor)", () => {
    expect(isDraggableElement(element({ id: "x", type: "group" }))).toBe(false);
  });
});

describe("isContentPlaceholderElement", () => {
  it("is true for image/shape/table/reportifyr/quarto -- no real content preview on this canvas", () => {
    for (const type of ["image", "shape", "table", "reportifyr", "quarto"] as const) {
      expect(isContentPlaceholderElement(element({ id: "x", type }))).toBe(true);
    }
  });

  it("is false for text/markdown -- real, previewable prose", () => {
    expect(isContentPlaceholderElement(element({ id: "x", type: "text" }))).toBe(false);
    expect(isContentPlaceholderElement(element({ id: "x", type: "markdown" }))).toBe(false);
  });

  it("is false for a layout zone's slot/footnotes types, even though they have no value either", () => {
    // Regression guard: an earlier draft of this helper generalized to
    // "not text/markdown", which incidentally swept in Layouts mode's
    // `slot`/`footnotes` zone types too (issue #30) -- silently
    // changing their on-canvas look (an empty box) to a labeled
    // placeholder, staling man/figures/web-app-layout-tab.png. `slot`/
    // `footnotes` must render exactly as before issue #54.
    //
    // `as unknown as ElementType`: a real `GET /api/layouts` zone can
    // carry `type: "slot"`/`"footnotes"` (see `NewElementBody`'s own
    // wider `ElementType | "slot" | "footnotes"` union, and
    // `ElementList.tsx`'s `LAYOUT_ONLY_TYPES`), but `ResolvedElement
    // .type` here is still typed as plain `ElementType` -- a pre-
    // existing type-safety gap, not introduced by this change.
    expect(
      isContentPlaceholderElement(element({ id: "x", type: "slot" as unknown as ElementType }))
    ).toBe(false);
    expect(
      isContentPlaceholderElement(
        element({ id: "x", type: "footnotes" as unknown as ElementType })
      )
    ).toBe(false);
  });

  it("is fixed (not draggable) for a furniture element even though its type is draggable", () => {
    // The actual bug this covers: a __furniture_status element has
    // type "text" (draggable-looking), but PATCHing it 404s since it
    // has no per-slide entry in presentation.yaml -- dragging one must
    // not even be attempted.
    expect(
      isDraggableElement(element({ id: "__furniture_status", type: "text" }))
    ).toBe(false);
    expect(
      isDraggableElement(element({ id: "__furniture_background", type: "image" }))
    ).toBe(false);
  });
});

describe("isDraggableFurnitureElement", () => {
  // The furniture pseudo-slide (issue #21) is the one context where
  // furniture elements *are* draggable -- the opposite of
  // isDraggableElement above, except for background, which has no `box`
  // field in design.yaml's schema at all (it always fills the slide) so
  // it stays fixed even there.
  it("is draggable for status/branding/page-number, but not background", () => {
    expect(isDraggableFurnitureElement(element({ id: "__furniture_status", type: "text" }))).toBe(
      true
    );
    expect(
      isDraggableFurnitureElement(element({ id: "__furniture_branding", type: "text" }))
    ).toBe(true);
    expect(
      isDraggableFurnitureElement(element({ id: "__furniture_page_number", type: "text" }))
    ).toBe(true);
    expect(
      isDraggableFurnitureElement(element({ id: "__furniture_background", type: "image" }))
    ).toBe(false);
  });

  it("still respects the ordinary draggable-type set", () => {
    expect(isDraggableFurnitureElement(element({ id: "x", type: "group" }))).toBe(false);
  });
});

describe("furnitureElementSupportsRotation / furnitureElementSupportsZIndex", () => {
  // Only StatusIndicatorStyle has rotation/z_index fields in design.yaml's
  // schema -- BrandingFurniture/PageNumberFurniture don't, and the
  // backend hard-rejects a patch that tries to set either there, so the
  // frontend must know not to send them.
  it("only __furniture_status supports rotation and z_index", () => {
    expect(furnitureElementSupportsRotation("__furniture_status")).toBe(true);
    expect(furnitureElementSupportsZIndex("__furniture_status")).toBe(true);

    for (const id of ["__furniture_branding", "__furniture_page_number", "__furniture_background"]) {
      expect(furnitureElementSupportsRotation(id)).toBe(false);
      expect(furnitureElementSupportsZIndex(id)).toBe(false);
    }
  });
});

describe("furnitureElementSupportsValue", () => {
  // Regression: __furniture_status/__furniture_page_number both render
  // as ordinary-looking text on the furniture pseudo-slide, but their
  // displayed text is computed from presentation.yaml (watermark/
  // metadata.status, or a {page}/{total} format string), not a literal
  // design.yaml field -- double-clicking to edit it must not be offered
  // for either. Only __furniture_branding has a real editable `text`.
  it("is true only for __furniture_branding", () => {
    expect(furnitureElementSupportsValue("__furniture_branding")).toBe(true);
    expect(furnitureElementSupportsValue("__furniture_status")).toBe(false);
    expect(furnitureElementSupportsValue("__furniture_page_number")).toBe(false);
    expect(furnitureElementSupportsValue("__furniture_background")).toBe(false);
  });
});

describe("applyTextTransform / displayText", () => {
  // Regression: the canvas preview showed a watermark's raw
  // `metadata.status` word ("demo") instead of the built deck's actual
  // "DEMO" -- text_transform (TextStyle.opacity's sibling field) was
  // never applied in the preview, only in the real compositor.
  it("uppercases/lowercases/title-cases per text_transform", () => {
    expect(applyTextTransform("demo", "uppercase")).toBe("DEMO");
    expect(applyTextTransform("DEMO", "lowercase")).toBe("demo");
    expect(applyTextTransform("draft copy", "capitalize")).toBe("Draft Copy");
    expect(applyTextTransform("demo", null)).toBe("demo");
    expect(applyTextTransform("demo", undefined)).toBe("demo");
  });

  it("displayText applies the element's own style.text_transform to its resolved text", () => {
    const el = element({
      id: "__furniture_status",
      type: "text",
      value: "demo",
      style: {
        font: "Arial",
        size_pt: 96,
        bold: false,
        italic: false,
        color: "#000000",
        opacity: 0.28,
        text_transform: "uppercase",
      },
    });
    expect(displayText(el)).toBe("DEMO");
  });
});

describe("konvaTextAlign / konvaVerticalAlign", () => {
  // Regression: a watermark (`center: true`, `align: null`) rendered
  // top-left on the canvas instead of centered in its box, making a
  // correctly-configured, centered-by-design element look like it was
  // positioned arbitrarily.
  it("center alone centers both axes", () => {
    const el = element({ center: true, align: null });
    expect(konvaTextAlign(el)).toBe("center");
    expect(konvaVerticalAlign(el)).toBe("middle");
  });

  it("align overrides the horizontal axis independently of center", () => {
    const el = element({ center: true, align: "right" });
    expect(konvaTextAlign(el)).toBe("right");
    expect(konvaVerticalAlign(el)).toBe("middle");
  });

  it("defaults to left/top when neither is set", () => {
    const el = element({ center: false, align: null });
    expect(konvaTextAlign(el)).toBe("left");
    expect(konvaVerticalAlign(el)).toBe("top");
  });
});

describe("centerToTopLeftPx", () => {
  // Regression: a real user reported a configured corner-tr status
  // placement ("test") being nowhere visible on the furniture
  // pseudo-slide -- traced to Konva rotating draggable Groups around
  // their top-left corner while python-pptx/OOXML rotates around the
  // shape's center, so a rotated box preview ended up at the wrong
  // location relative to the real build.
  it("converts a center point back to the box's top-left corner", () => {
    expect(centerToTopLeftPx(100, 50, 40, 20)).toEqual({ x: 80, y: 40 });
  });

  it("is a no-op inverse of x + width/2, y + height/2", () => {
    const x = 12.5;
    const y = 33;
    const width = 200;
    const height = 60;
    const center = { x: x + width / 2, y: y + height / 2 };
    expect(centerToTopLeftPx(center.x, center.y, width, height)).toEqual({ x, y });
  });
});

describe("elementLabel", () => {
  it("labels a furniture element by its stripped, human-readable suffix", () => {
    expect(elementLabel(element({ id: "__furniture_status", type: "text" }))).toBe(
      "furniture: status"
    );
    expect(elementLabel(element({ id: "__furniture_page_number", type: "text" }))).toBe(
      "furniture: page_number"
    );
  });

  it("labels an ordinary image element by its source path", () => {
    expect(elementLabel(element({ id: "pic", type: "image", source: "logo.png" }))).toBe(
      "image: logo.png"
    );
  });

  it("labels any other ordinary element as type: id", () => {
    expect(elementLabel(element({ id: "box1", type: "shape" }))).toBe("shape: box1");
  });
});
