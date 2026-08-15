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
import { boxToInches, inchesToPixels, pixelsToInches, resolveKonvaTransformToInches } from "../geometry";
import type { ElementPatchBody, ResolvedElement } from "../types";

const DRAGGABLE_TYPES = new Set(["text", "markdown", "image"]);

// `__furniture_background`/`__furniture_status`/`__furniture_branding`/
// `__furniture_page_number` (`inst/python/deckifyr/plan.py`'s own
// `_FURNITURE_*_ID` constants) are synthesized once per slide at
// plan-time from `design.yaml`'s `furniture` block + `presentation.yaml`'s
// top-level `status_indicator` -- they don't exist in any slide's own
// `elements` in the raw `presentation.yaml`, so `PATCH
// /api/slides/{id}/elements/{id}` has nothing to find for one (a real
// 404, confirmed against the API) and dragging one is a dead end no
// matter its `type`. They render fixed (like the other non-draggable
// placeholder types below) instead -- deck-wide options belong in
// `DeckOptions`/the Config tab, not as a draggable per-slide element.
const FURNITURE_PREFIX = "__furniture_";

// Exported for direct unit testing (`SlideCanvas.logic.test.ts`) --
// pure functions of an element, no DOM/Konva involved.
export function isFurnitureElement(element: ResolvedElement): boolean {
  return element.id.startsWith(FURNITURE_PREFIX);
}

export function isDraggableElement(element: ResolvedElement): boolean {
  return DRAGGABLE_TYPES.has(element.type) && !isFurnitureElement(element);
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

interface Props {
  plan: UsePlanResult;
}

export default function SlideCanvas({ plan }: Props) {
  const { state, dispatch } = useAppContext();
  const { slides, slideSize } = plan;
  const [editingElementId, setEditingElementId] = useState<string | null>(null);
  const [editingValue, setEditingValue] = useState("");
  const [mutationError, setMutationError] = useState<string | null>(null);

  const shapeRefs = useRef<Record<string, Konva.Node>>({});
  const transformerRef = useRef<Konva.Transformer>(null);

  const slide = slides?.find((s) => s.id === state.selectedSlideId) ?? slides?.[0];
  const selectedElement = findElement(slide, state.selectedElementId);

  useEffect(() => {
    const transformer = transformerRef.current;
    if (!transformer) return;
    const node =
      state.selectedElementId && selectedElement && isDraggableElement(selectedElement)
        ? shapeRefs.current[state.selectedElementId]
        : undefined;
    transformer.nodes(node ? [node] : []);
    transformer.getLayer()?.batchDraw();
  }, [state.selectedElementId, selectedElement?.type, slide]);

  // `plan.error` must be checked before the loading fallback below --
  // once a fetch fails, `plan.loading` settles to `false` but `slides`/
  // `slideSize` stay `null` forever, so without this check the canvas
  // was stuck showing "Loading plan…" indefinitely instead of the real
  // error (caught by screenshotting a failed fetch, not by reasoning
  // about the state machine in the abstract).
  if (plan.error) {
    return (
      <div className="slide-canvas slide-canvas--empty" role="alert">
        {plan.error}
      </div>
    );
  }
  if (!slides || !slideSize) {
    return <div className="slide-canvas slide-canvas--loading">Loading plan…</div>;
  }
  if (!slide) {
    return <div className="slide-canvas slide-canvas--empty">No slides.</div>;
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
  const visibleElements = state.showFurniture
    ? slide.elements
    : slide.elements.filter((element) => !isFurnitureElement(element));

  function selectOrEdit(element: ResolvedElement) {
    if (state.selectedElementId === element.id && isDraggableElement(element) && element.type !== "image") {
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
    const xIn = pixelsToInches(node.x(), 1);
    const yIn = pixelsToInches(node.y(), 1);
    await commitPatch(element, { box: { x: xIn, y: yIn } }, "move");
  }

  async function handleTransformEnd(element: ResolvedElement, node: Konva.Node) {
    const resolved = resolveKonvaTransformToInches(
      {
        x: node.x(),
        y: node.y(),
        width: node.width(),
        height: node.height(),
        scaleX: node.scaleX(),
        scaleY: node.scaleY(),
        rotation: node.rotation(),
      },
      1
    );
    await commitPatch(
      element,
      {
        box: { x: resolved.x, y: resolved.y, width: resolved.width, height: resolved.height },
        rotation: resolved.rotation,
      },
      "resize/rotate"
    );
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
              const isDraggable = isDraggableElement(element);
              const isFurniture = isFurnitureElement(element);

              if (!isDraggable) {
                return (
                  <Group key={element.id} x={x} y={y} rotation={element.rotation}>
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
                  x={x}
                  y={y}
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
                    text={element.type === "image" ? elementLabel(element) : plainText(element)}
                    width={width}
                    height={height}
                    padding={4}
                    fontSize={element.style?.size_pt ?? 14}
                    fontStyle={element.style?.bold ? "bold" : "normal"}
                    fill={element.style?.color ?? "#202124"}
                    wrap="word"
                    listening={false}
                  />
                </Group>
              );
            })}
            <Transformer
              ref={transformerRef}
              rotateEnabled
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
