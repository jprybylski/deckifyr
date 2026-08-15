import { describe, expect, it } from "vitest";
import { elementLabel, isDraggableElement, isFurnitureElement } from "./SlideCanvas";
import type { ResolvedElement } from "../types";

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
  it("is draggable for ordinary text/markdown/image elements", () => {
    expect(isDraggableElement(element({ id: "title", type: "text" }))).toBe(true);
    expect(isDraggableElement(element({ id: "body", type: "markdown" }))).toBe(true);
    expect(isDraggableElement(element({ id: "pic", type: "image" }))).toBe(true);
  });

  it("is never draggable for shape/group/table/reportifyr/quarto elements", () => {
    for (const type of ["shape", "group", "table", "reportifyr", "quarto"] as const) {
      expect(isDraggableElement(element({ id: "x", type }))).toBe(false);
    }
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
