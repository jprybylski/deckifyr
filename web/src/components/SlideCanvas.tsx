/**
 * Renders the selected slide's elements on a Konva `Stage`/`Layer`
 * sized to `design.yaml`'s own `slide.width`/`slide.height` (fetched,
 * along with `/api/plan`, by `state/usePlan.ts`).
 *
 * Zoom is implemented as the *Stage's own* `scaleX`/`scaleY` (plus a
 * matching outer pixel size) rather than pre-multiplying every node's
 * geometry by the zoom factor -- Konva already compensates pointer/
 * transform coordinates for a scaled Stage, so every node's `x`/`y`/
 * `width`/`height`/`scaleX`/`scaleY` stays in the *same* "1 zoom" pixel
 * space regardless of the toolbar zoom level (`geometry.ts`'s
 * `inchesToPixels(value, 1)` throughout this file). The one place the
 * real zoom factor matters is the DOM `<textarea>` overlay below, which
 * is plain HTML positioned on top of the canvas, not a Konva node, so
 * it has no built-in scale compensation of its own.
 *
 * `shape`/`group`/`table`/`reportifyr`/`quarto` elements render as a
 * static, labeled, dashed placeholder box (per this project's scope --
 * only `text`/`markdown`/`image` are draggable/resizable/rotatable).
 * `image` elements are draggable/resizable/rotatable like text, but
 * there is no endpoint in today's API contract to fetch a project
 * image's actual pixels (`GET /api/plan` only returns its `source`
 * path) -- so an `image` element renders as a labeled placeholder box
 * too, just one that participates in drag/resize/rotate like a real
 * image would once that endpoint exists.
 */
import { useEffect, useRef, useState } from "react";
import { Stage, Layer, Rect, Text as KonvaText, Transformer, Group } from "react-konva";
import type Konva from "konva";
import { useAppContext } from "../state/AppContext";
import { findElement, inverseForBoxPatch, type UsePlanResult } from "../state/usePlan";
import {
  boxPixelsToInches,
  boxToInches,
  inchesToPixels,
  pixelsToInches,
  resolveKonvaTransform,
} from "../geometry";
import type { ElementPatchBody, ResolvedElement } from "../types";

const DRAGGABLE_TYPES = new Set(["text", "markdown", "image"]);

// `__furniture_background`/`__furniture_status`/`__furniture_branding`/
// `__furniture_page_number` (`inst/python/deckifyr/plan.py`'s own
// `FURNITURE_*_ID` constants) are synthesized once per slide at
// plan-time from `design.yaml`'s `furniture` block + `presentation.yaml`'s
// top-level `status_indicator`. On an ordinary real slide they don't
// exist in that slide's own `elements` in `presentation.yaml`, so `PATCH
// /api/slides/{id}/elements/{id}` has nothing to find for one and
// dragging one there is a dead end no matter its `type` -- they render
// fixed there, like the other non-draggable placeholder types below.
// On the furniture *pseudo*-slide (`plan.furnitureSlide`, id
// `FURNITURE_SLIDE_ID`, issue #21) the opposite is true: these are the
// only elements present, and they're exactly what that pseudo-slide
// exists to let you drag/resize/rotate -- see `isDraggableFurnitureElement`
// below, and `usePlan.ts`'s `sendPatch` for where the resulting PATCH
// actually goes (`design.yaml`, not `presentation.yaml`).
const FURNITURE_PREFIX = "__furniture_";

// Exported for direct unit testing (`SlideCanvas.logic.test.ts`) --
// pure functions of an element, no DOM/Konva involved.
export function isFurnitureElement(element: ResolvedElement): boolean {
  return element.id.startsWith(FURNITURE_PREFIX);
}

export function isDraggableElement(element: ResolvedElement): boolean {
  return DRAGGABLE_TYPES.has(element.type) && !isFurnitureElement(element);
}

// `__furniture_background` has no `box` field at all in `design.yaml`'s
// schema (`SlideSize.background_image` is just a path -- it always fills
// the slide), so it stays a fixed placeholder even on the furniture
// pseudo-slide; the other three furniture kinds each have a real `box`
// (`StatusIndicatorStyle`/`BrandingFurniture`/`PageNumberFurniture`) and
// become draggable there.
export function isDraggableFurnitureElement(element: ResolvedElement): boolean {
  return DRAGGABLE_TYPES.has(element.type) && element.id !== "__furniture_background";
}

// Only `StatusIndicatorStyle` (the `__furniture_status` element) has a
// `rotation`/`z_index` field in `design.yaml`'s schema -- branding/
// page-number don't, and the backend hard-rejects (422) a patch that
// tries to set either there rather than silently dropping it (spec
// section 20 warning 7's "no silent magic"), so the frontend must not
// send those fields for anything but status while on the furniture
// pseudo-slide.
export function furnitureElementSupportsRotation(elementId: string): boolean {
  return elementId === "__furniture_status";
}

export function furnitureElementSupportsZIndex(elementId: string): boolean {
  return elementId === "__furniture_status";
}

// `__furniture_branding` is the only furniture kind with a plain
// editable string in the schema (`BrandingFurniture.text`) -- the
// backend maps its PATCH `value` straight onto that field.
// `__furniture_status`'s displayed text is *not* a `design.yaml` field
// at all: it's `presentation.yaml`'s own `watermark`/`metadata.status`
// (`deckifyr.plan.resolve_watermark_text`), so there's nothing here to
// PATCH even though the element's `value` looks like ordinary text --
// double-clicking to edit it must not even be offered.
// `__furniture_page_number`'s displayed text is `format.format(page=,
// total=)`, a computed string, not a literal one -- also not
// value-editable here (`format` itself stays Config-tab-only, since a
// placeholder-aware textarea is a bigger feature than this slice needs).
export function furnitureElementSupportsValue(elementId: string): boolean {
  return elementId === "__furniture_branding";
}

// Layouts editor mode (issue #30, originally issue #23's since-
// superseded per-slide Content/Layout tab): every zone is draggable
// regardless of its `type` -- unlike `isDraggableElement`, which only
// allows `text`/`markdown`/`image`. A layout zone is a pure position
// slot (`layouts.yaml`'s own `slot`/`footnotes` types have no content of
// their own at all, spec section 7.5), so gating on `DRAGGABLE_TYPES`
// the way ordinary slide content is would make most of a typical
// layout's own zones (its `slot`/`footnotes` entries) immovable,
// defeating the point of this mode.
export function isDraggableLayoutZone(): boolean {
  return true;
}

export function elementLabel(element: ResolvedElement): string {
  if (isFurnitureElement(element)) {
    return `furniture: ${element.id.slice(FURNITURE_PREFIX.length)}`;
  }
  if (element.type === "image") return `image: ${element.source ?? "?"}`;
  return `${element.type}: ${element.id}`;
}

function plainText(element: ResolvedElement): string {
  const raw = typeof element.value === "string" ? element.value : "";
  if (element.type !== "markdown") return raw;
  // Deliberately not a real Markdown renderer (out of scope, see this
  // repo's own compositor for the real one) -- just enough to strip the
  // most common inline markers so a canvas preview doesn't show literal
  // `#`/`**` characters.
  return raw.replace(/^#+\s*/gm, "").replace(/\*\*(.*?)\*\*/g, "$1").replace(/[*_]/g, "");
}

// Mirrors `deckifyr.pptx.compose._apply_text_transform` (a plain
// `str.upper()`/`.lower()`/`.title()`), applied after markdown's own
// formatting markers are already stripped -- same order the real
// compositor applies it in. A preview-quality approximation of Python's
// `.title()` for "capitalize" (doesn't handle every apostrophe/hyphen
// edge case the same way) -- good enough for what this canvas is for:
// seeing roughly what a status/watermark word will look like, not
// byte-exact output (that's what the real build/preview render).
export function applyTextTransform(text: string, transform: string | null | undefined): string {
  switch (transform) {
    case "uppercase":
      return text.toUpperCase();
    case "lowercase":
      return text.toLowerCase();
    case "capitalize":
      return text.replace(
        /\S+/g,
        (word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
      );
    default:
      return text;
  }
}

export function displayText(element: ResolvedElement): string {
  return applyTextTransform(plainText(element), element.style?.text_transform);
}

// Mirrors `deckifyr.pptx.compose._add_text_shape`'s own alignment
// resolution: `center` alone means "center both axes" (the watermark's
// own default, spec section 7.8), `align` overrides the horizontal axis
// independently (issue #13's corner placements: right/left-flush while
// still vertically centered) -- see `Element.align`'s own docstring for
// why the two fields are independent rather than one bool.
export function konvaTextAlign(element: ResolvedElement): "left" | "center" | "right" {
  if (element.align === "left" || element.align === "center" || element.align === "right") {
    return element.align;
  }
  return element.center ? "center" : "left";
}

export function konvaVerticalAlign(element: ResolvedElement): "top" | "middle" {
  return element.center ? "middle" : "top";
}

// Every draggable (and fixed-placeholder) Group below is positioned/
// rotated around its own *center* (`x + width/2, y + height/2` with a
// matching `offsetX`/`offsetY`), not its top-left corner -- matching
// how `python-pptx`/OOXML's `<a:xfrm rot="...">` actually rotates a
// shape (around its own center), confirmed against
// `deckifyr.pptx.compose` (every `shape.rotation = element.rotation`
// there sets that same OOXML attribute). Konva's *default* rotation
// pivot is the node's `(x,y)` itself (no offset), which would rotate
// around the top-left corner instead -- a real, confirmed mismatch: a
// rotated corner placement (`furniture.status.corner_tr`,
// `rotation: -90`) swung to a completely different, often off-canvas
// position under Konva's default versus PowerPoint's actual
// center-pivot behavior (the actual bug a user hit -- a configured
// corner placement's text was nowhere to be found on the furniture
// pseudo-slide). `handleDragEnd`/`handleTransformEnd` read `node.x()`/
// `node.y()` as this center and must convert back to top-left before
// building a box patch, since the schema (and every other box field in
// this app) stores top-left `x`/`y`.
export function centerToTopLeftPx(
  centerXPx: number,
  centerYPx: number,
  widthPx: number,
  heightPx: number
): { x: number; y: number } {
  return { x: centerXPx - widthPx / 2, y: centerYPx - heightPx / 2 };
}

interface Props {
  plan: UsePlanResult;
}

export default function SlideCanvas({ plan }: Props) {
  const { state, dispatch } = useAppContext();
  const { slides, furnitureSlide, layouts, slideSize } = plan;
  const [editingElementId, setEditingElementId] = useState<string | null>(null);
  const [editingValue, setEditingValue] = useState("");
  const [mutationError, setMutationError] = useState<string | null>(null);

  const shapeRefs = useRef<Record<string, Konva.Node>>({});
  const transformerRef = useRef<Konva.Transformer>(null);

  const isFurnitureSlideSelected =
    furnitureSlide !== null && state.selectedSlideId === furnitureSlide.id;
  // Issue #30: which collection `state.selectedSlideId` is looked up
  // in is now a persistent, app-wide choice (`state.editorMode`), not a
  // per-slide toggle -- so, unlike the superseded `layoutSlide`/
  // `loadLayoutZones` this replaces, there's no on-demand fetch and no
  // staleness race to guard against: `plan.layouts` is fetched in full,
  // eagerly, the same as `plan.slides`.
  const isLayoutsMode = !isFurnitureSlideSelected && state.editorMode === "layouts";
  const slide = isFurnitureSlideSelected
    ? furnitureSlide
    : isLayoutsMode
      ? (layouts?.find((l) => l.id === state.selectedSlideId) ?? layouts?.[0])
      : (slides?.find((s) => s.id === state.selectedSlideId) ?? slides?.[0]);
  const selectedElement = findElement(slide, state.selectedElementId);

  // On the furniture pseudo-slide, `background` stays a fixed
  // placeholder (no `box` field to drag) but `status`/`branding`/
  // `page_number` all become draggable -- the opposite of an ordinary
  // real slide, where every `__furniture_*` element is fixed. In
  // Layouts mode, every zone is draggable regardless of type (see
  // `isDraggableLayoutZone`'s own comment for why).
  const isDraggable = isFurnitureSlideSelected
    ? isDraggableFurnitureElement
    : isLayoutsMode
      ? isDraggableLayoutZone
      : isDraggableElement;

  useEffect(() => {
    const transformer = transformerRef.current;
    if (!transformer) return;
    const node =
      state.selectedElementId && selectedElement && isDraggable(selectedElement)
        ? shapeRefs.current[state.selectedElementId]
        : undefined;
    transformer.nodes(node ? [node] : []);
    transformer.getLayer()?.batchDraw();
  }, [state.selectedElementId, selectedElement?.type, slide, isDraggable]);

  // `plan.error` must be checked before the loading fallback below --
  // once a fetch fails, `plan.loading` settles to `false` but `slides`/
  // `slideSize` stay `null` forever, so without this check the canvas
  // was stuck showing "Loading plan…" indefinitely instead of the real
  // error (caught by screenshotting a failed fetch, not by reasoning
  // about the state machine in the abstract).
  //
  // On the furniture pseudo-slide specifically, a `plan.error` (almost
  // always `GET /api/plan` failing because `status_indicator` points at
  // a placement design.yaml hasn't styled yet -- `usePlan.ts`'s
  // `Promise.allSettled` note) must NOT block this screen: it's the one
  // place that error is actually fixable (`FurnitureControls`' "Add"),
  // and `GET /api/furniture` is deliberately lenient about that exact
  // case, so `furnitureSlide`/`slideSize` are still real, current data
  // even while `plan.error` is set. A real error banner still shows
  // below instead, so the reason the real slides are broken stays
  // visible.
  const furnitureSlideUsable = isFurnitureSlideSelected && furnitureSlide && slideSize;
  // Layouts mode depends on `plan.layouts`, not `plan.slides` -- an
  // unrelated real-slide plan failure (`plan.error`) must not block it
  // either, same carve-out `furnitureSlideUsable` above already has.
  const layoutsModeUsable = isLayoutsMode && layouts && slideSize;
  if (plan.error && !furnitureSlideUsable && !layoutsModeUsable) {
    return (
      <div className="slide-canvas slide-canvas--empty" role="alert">
        {plan.error}
      </div>
    );
  }
  if (
    !slideSize ||
    (!isFurnitureSlideSelected && (isLayoutsMode ? !layouts : !slides))
  ) {
    return <div className="slide-canvas slide-canvas--loading">Loading plan…</div>;
  }
  if (!slide) {
    return <div className="slide-canvas slide-canvas--empty">No slides.</div>;
  }
  if (isLayoutsMode && slide.elements.length === 0) {
    return (
      <div className="slide-canvas slide-canvas--empty">
        This layout has no zones defined yet.
      </div>
    );
  }

  const zoom = state.zoom;
  const baseWidthPx = inchesToPixels(slideSize.widthIn, 1);
  const baseHeightPx = inchesToPixels(slideSize.heightIn, 1);
  // A pure view-time filter, not a data change -- `slide.elements` itself
  // is untouched (ElementInspector/undo-redo/etc. still see furniture via
  // the full plan), this only decides what SlideCanvas paints. Distinct
  // from DeckOptions' status_indicator toggle: that one is persisted to
  // presentation.yaml and changes what the *built* deck looks like;
  // `showFurniture` never leaves the browser and exists specifically so
  // the always-on-top watermark/status furniture (z_index 9999) doesn't
  // sit in the way while dragging/selecting real slide content.
  const visibleElements = isFurnitureSlideSelected
    ? // `hiddenFurnitureIds` (issue #21 follow-up): a per-item, client-
      // only visibility toggle scoped to this pseudo-slide, so a large
      // watermark can be tucked out of the way while positioning
      // branding/page-number without deleting its configured style
      // (that's `FurnitureControls`' separate "Remove" action).
      slide.elements.filter((element) => !state.hiddenFurnitureIds.includes(element.id))
    : state.showFurniture
      ? slide.elements
      : slide.elements.filter((element) => !isFurnitureElement(element));

  function selectOrEdit(element: ResolvedElement) {
    const canEditValue =
      !isFurnitureSlideSelected || furnitureElementSupportsValue(element.id);
    if (
      state.selectedElementId === element.id &&
      isDraggable(element) &&
      element.type !== "image" &&
      canEditValue
    ) {
      setEditingElementId(element.id);
      setEditingValue(typeof element.value === "string" ? element.value : "");
    } else {
      dispatch({ type: "SELECT_ELEMENT", elementId: element.id });
    }
  }

  async function commitPatch(
    element: ResolvedElement,
    patch: ElementPatchBody,
    label: string
  ) {
    const inverse = inverseForBoxPatch(element, patch);
    try {
      await plan.applyElementPatch(slide!.id, element.id, patch, inverse, label);
      setMutationError(null);
    } catch (err) {
      setMutationError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleDragEnd(element: ResolvedElement, node: Konva.Node) {
    const topLeftPx = centerToTopLeftPx(node.x(), node.y(), node.width(), node.height());
    const xIn = pixelsToInches(topLeftPx.x, 1);
    const yIn = pixelsToInches(topLeftPx.y, 1);
    await commitPatch(element, { box: { x: xIn, y: yIn } }, "move");
  }

  async function handleTransformEnd(element: ResolvedElement, node: Konva.Node) {
    const resolvedPx = resolveKonvaTransform({
      x: node.x(),
      y: node.y(),
      width: node.width(),
      height: node.height(),
      scaleX: node.scaleX(),
      scaleY: node.scaleY(),
      rotation: node.rotation(),
    });
    const topLeftPx = centerToTopLeftPx(resolvedPx.x, resolvedPx.y, resolvedPx.width, resolvedPx.height);
    const resolved = {
      ...boxPixelsToInches(
        { x: topLeftPx.x, y: topLeftPx.y, width: resolvedPx.width, height: resolvedPx.height },
        1
      ),
      rotation: resolvedPx.rotation,
    };
    const patch: ElementPatchBody = {
      box: { x: resolved.x, y: resolved.y, width: resolved.width, height: resolved.height },
    };
    // Only `__furniture_status` has a `rotation` field in design.yaml's
    // schema (branding/page-number don't) -- the backend hard-rejects
    // any other furniture kind's rotation patch, so this must not send
    // one. Konva's Transformer already keeps `rotateEnabled` off for
    // those (see below), so `node.rotation()` would be 0 anyway; this
    // is the belt to that suspenders.
    if (!isFurnitureSlideSelected || furnitureElementSupportsRotation(element.id)) {
      patch.rotation = resolved.rotation;
    }
    await commitPatch(element, patch, "resize/rotate");
  }

  async function commitTextEdit() {
    if (!editingElementId) return;
    const element = findElement(slide, editingElementId);
    setEditingElementId(null);
    if (!element) return;
    const previousValue = typeof element.value === "string" ? element.value : "";
    if (previousValue === editingValue) return;
    await commitPatch(element, { value: editingValue }, "edit text");
  }

  const editingElement = findElement(slide, editingElementId);

  return (
    <div className="slide-canvas">
      {isFurnitureSlideSelected && plan.error && (
        <div className="slide-canvas__warning" role="alert">
          Real slides currently fail to render: {plan.error} -- use the
          Furniture panel above to Add the missing placement, or change
          Status indicator in Deck Options.
        </div>
      )}
      {mutationError && (
        <div className="slide-canvas__error" role="alert">
          {mutationError}
        </div>
      )}
      <div
        className="slide-canvas__stage-wrap"
        style={{
          position: "relative",
          width: baseWidthPx * zoom,
          height: baseHeightPx * zoom,
        }}
      >
        <Stage
          width={baseWidthPx * zoom}
          height={baseHeightPx * zoom}
          scaleX={zoom}
          scaleY={zoom}
          onMouseDown={(e) => {
            if (e.target === e.target.getStage()) {
              dispatch({ type: "SELECT_ELEMENT", elementId: null });
              setEditingElementId(null);
            }
          }}
        >
          <Layer>
            <Rect
              x={0}
              y={0}
              width={baseWidthPx}
              height={baseHeightPx}
              fill="#ffffff"
              stroke="#cccccc"
            />
            {visibleElements.map((element) => {
              const box = boxToInches(element.box);
              const x = inchesToPixels(box.x, 1);
              const y = inchesToPixels(box.y, 1);
              const width = inchesToPixels(box.width, 1);
              const height = inchesToPixels(box.height, 1);
              const isSelected = state.selectedElementId === element.id;
              const draggable = isDraggable(element);
              const isFurniture = isFurnitureElement(element);

              if (!draggable) {
                return (
                  <Group
                    key={element.id}
                    x={x + width / 2}
                    y={y + height / 2}
                    offsetX={width / 2}
                    offsetY={height / 2}
                    rotation={element.rotation}
                  >
                    <Rect
                      width={width}
                      height={height}
                      fill={isFurniture ? "#eef2f7" : "#f2f2f2"}
                      stroke={isSelected ? "#2457a6" : isFurniture ? "#7a93b8" : "#999999"}
                      dash={[6, 4]}
                      onClick={() => dispatch({ type: "SELECT_ELEMENT", elementId: element.id })}
                      onTap={() => dispatch({ type: "SELECT_ELEMENT", elementId: element.id })}
                    />
                    <KonvaText
                      text={elementLabel(element)}
                      width={width}
                      height={height}
                      align="center"
                      verticalAlign="middle"
                      fontSize={12}
                      fill="#666666"
                      listening={false}
                    />
                  </Group>
                );
              }

              return (
                <Group
                  key={element.id}
                  ref={(node) => {
                    if (node) shapeRefs.current[element.id] = node;
                    else delete shapeRefs.current[element.id];
                  }}
                  x={x + width / 2}
                  y={y + height / 2}
                  offsetX={width / 2}
                  offsetY={height / 2}
                  width={width}
                  height={height}
                  rotation={element.rotation}
                  scaleX={1}
                  scaleY={1}
                  draggable
                  onClick={() => selectOrEdit(element)}
                  onTap={() => selectOrEdit(element)}
                  onDragEnd={(e) => handleDragEnd(element, e.target)}
                  onTransformEnd={(e) => handleTransformEnd(element, e.target)}
                >
                  <Rect
                    width={width}
                    height={height}
                    fill={element.type === "image" ? "#e8eef7" : "#ffffff"}
                    stroke={isSelected ? "#2457a6" : "#dddddd"}
                    strokeWidth={isSelected ? 2 : 1}
                  />
                  <KonvaText
                    text={element.type === "image" ? elementLabel(element) : displayText(element)}
                    width={width}
                    height={height}
                    padding={4}
                    fontSize={element.style?.size_pt ?? 14}
                    fontStyle={element.style?.bold ? "bold" : "normal"}
                    fill={element.style?.color ?? "#202124"}
                    opacity={element.style?.opacity ?? 1}
                    align={element.type === "image" ? "left" : konvaTextAlign(element)}
                    verticalAlign={element.type === "image" ? "top" : konvaVerticalAlign(element)}
                    wrap="word"
                    listening={false}
                  />
                </Group>
              );
            })}
            <Transformer
              ref={transformerRef}
              rotateEnabled={
                !isFurnitureSlideSelected ||
                !selectedElement ||
                furnitureElementSupportsRotation(selectedElement.id)
              }
              boundBoxFunc={(oldBox, newBox) =>
                newBox.width < 5 || newBox.height < 5 ? oldBox : newBox
              }
            />
          </Layer>
        </Stage>

        {editingElement && (
          <textarea
            className="slide-canvas__text-overlay"
            autoFocus
            value={editingValue}
            onChange={(e) => setEditingValue(e.target.value)}
            onBlur={() => void commitTextEdit()}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void commitTextEdit();
              } else if (e.key === "Escape") {
                setEditingElementId(null);
              }
            }}
            style={{
              position: "absolute",
              left: inchesToPixels(boxToInches(editingElement.box).x, zoom),
              top: inchesToPixels(boxToInches(editingElement.box).y, zoom),
              width: inchesToPixels(boxToInches(editingElement.box).width, zoom),
              height: inchesToPixels(boxToInches(editingElement.box).height, zoom),
              fontSize: (editingElement.style?.size_pt ?? 14) * zoom,
            }}
          />
        )}
      </div>
    </div>
  );
}
