/**
 * Right-hand sidebar listing every element on the currently selected
 * slide/layout/furniture pseudo-slide (issue #31), collapsed by
 * default. Selecting a row -- or clicking the same element on
 * `SlideCanvas` -- expands it there via `state.selectedElementId`, the
 * one shared piece of selection state both already read/write; this
 * component owns no selection state of its own. The expanded content is
 * `ElementInspector`'s existing box/rotation/z-index form, rendered
 * inline for the selected row rather than in its own separate, always-
 * visible sidebar slot -- `App.tsx` no longer renders `ElementInspector`
 * on its own; this component does, once, for whichever row is expanded.
 *
 * "Add" lives once, below the whole list (issue's own "Add button can
 * be under the list"); each row's own "Remove" lives in that row
 * (issue's own "remove can be in the item"). Furniture elements are
 * never listed on an ordinary slide/layout -- they aren't something a
 * slide owns (`isFurnitureElement`, `SlideCanvas.tsx`), the same reason
 * `SlideList`'s own per-slide element count excludes them.
 *
 * On the furniture pseudo-slide, this component *is* the furniture
 * editor -- it replaces the standalone `FurnitureControls` bar that
 * used to sit above the canvas (issue's own "this would also offer a
 * better interface for furniture editing... instead of the Add/Remove/
 * Hide when the pseudo-slide is selected"). The four furniture kinds
 * are still added/removed through the same fixed-cardinality
 * `addFurnitureElement`/`removeFurnitureElement` routes
 * `FurnitureControls` always used -- furniture is deliberately not
 * generic element CRUD (`deckifyr.web.app`'s own routing comment) -- so
 * this keeps that mechanism, just presented as list rows instead of a
 * horizontal control strip.
 */
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import {
  ApiError,
  addFurnitureElement,
  getConfig,
  getProjectFiles,
  removeFurnitureElement,
} from "../api/client";
import { useAppContext } from "../state/AppContext";
import { isFurnitureElement } from "./SlideCanvas";
import { findElement, type UsePlanResult } from "../state/usePlan";
import type { NewElementBody, ResolvedSlide } from "../types";
import ElementInspector from "./ElementInspector";

interface Props {
  plan: UsePlanResult;
  /** See `FurnitureControls`'s own original docstring for why this
   * exists -- `DeckOptions` has no other way to learn its own
   * `status_indicator` copy just went stale after an Add/Remove here. */
  onStatusIndicatorChanged?: () => void;
}

// Mirrors `inst/python/deckifyr/plan.py`'s public `FURNITURE_*_ID`
// constants -- kept as plain literals here rather than imported, since
// there's no shared TS module for them yet (`SlideCanvas.tsx`'s
// `FURNITURE_PREFIX`/predicate helpers are exported today, the ids
// themselves aren't).
const FURNITURE_BACKGROUND_ID = "__furniture_background";
const FURNITURE_STATUS_ID = "__furniture_status";
const FURNITURE_BRANDING_ID = "__furniture_branding";
const FURNITURE_PAGE_NUMBER_ID = "__furniture_page_number";

const CONTENT_ELEMENT_TYPES = [
  "text",
  "markdown",
  "image",
  "shape",
  "group",
  "table",
  "reportifyr",
  "quarto",
] as const;

// Layout zones may additionally use the two zone-only types (spec
// section 7.5) -- neither is meaningful as an ordinary slide element.
const LAYOUT_ONLY_TYPES = ["slot", "footnotes"] as const;

// `deckifyr.schema.layouts.ShapeKind`'s own small, named subset of
// `MSO_SHAPE` -- kept in sync with that Python literal by hand (no
// shared schema-to-TS generation exists yet for this one enum).
const SHAPE_KINDS = [
  "rectangle",
  "rounded_rectangle",
  "oval",
  "triangle",
  "diamond",
  "pentagon",
  "hexagon",
  "chevron",
  "right_arrow",
  "left_arrow",
  "up_arrow",
  "down_arrow",
  "star_5",
] as const;

/** Client-only Hide/Show toggle (`state.hiddenFurnitureIds`,
 * `reducer.ts`) -- distinct from Remove, which deletes the item's style
 * from design.yaml. Shown only for the full-page watermark placement,
 * the one furniture kind large enough to visually bury branding/page-
 * number underneath it while positioning them. */
function StatusHideToggle() {
  const { state, dispatch } = useAppContext();
  const hidden = state.hiddenFurnitureIds.includes(FURNITURE_STATUS_ID);
  return (
    <button
      type="button"
      className="element-list__hide-toggle"
      onClick={() => dispatch({ type: "TOGGLE_FURNITURE_HIDDEN", elementId: FURNITURE_STATUS_ID })}
    >
      {hidden ? "Show" : "Hide"}
    </button>
  );
}

function AddElementForm({
  slide,
  isLayoutsMode,
  onAdd,
  onDone,
}: {
  slide: ResolvedSlide;
  isLayoutsMode: boolean;
  onAdd: (body: NewElementBody) => Promise<void>;
  onDone: () => void;
}) {
  const availableTypes = isLayoutsMode
    ? [...CONTENT_ELEMENT_TYPES, ...LAYOUT_ONLY_TYPES]
    : CONTENT_ELEMENT_TYPES;
  const [id, setId] = useState("");
  const [type, setType] = useState<string>(availableTypes[0]);
  const [value, setValue] = useState("");
  const [source, setSource] = useState("");
  const [shapeKind, setShapeKind] = useState<string>(SHAPE_KINDS[0]);
  const [projectFiles, setProjectFiles] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (type !== "reportifyr" && type !== "quarto") {
      setProjectFiles(null);
      return;
    }
    let cancelled = false;
    getProjectFiles(type)
      .then(({ files }) => {
        if (!cancelled) {
          setProjectFiles(files);
          setSource(files[0] ?? "");
        }
      })
      .catch(() => {
        if (!cancelled) setProjectFiles([]);
      });
    return () => {
      cancelled = true;
    };
  }, [type]);

  const existingIds = new Set(slide.elements.map((el) => el.id));

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!id.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const body: NewElementBody = { id: id.trim(), type: type as NewElementBody["type"] };
      if (type === "text" || type === "markdown") body.value = value;
      if (type === "image" || type === "table") body.source = source;
      if (type === "shape") body.shape_kind = shapeKind;
      if (type === "reportifyr") body.value = `{rpfy}:${source}`;
      if (type === "quarto") body.source = source;
      await onAdd(body);
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="element-list__add-form" onSubmit={(e) => void submit(e)}>
      <label>
        New element id
        <input value={id} onChange={(e) => setId(e.target.value)} autoFocus />
      </label>
      <label>
        Type
        <select value={type} onChange={(e) => setType(e.target.value)}>
          {availableTypes.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>
      {(type === "text" || type === "markdown") && (
        <label>
          Value
          <textarea value={value} onChange={(e) => setValue(e.target.value)} rows={3} />
        </label>
      )}
      {(type === "image" || type === "table") && (
        <label>
          Source (project-relative path)
          <input value={source} onChange={(e) => setSource(e.target.value)} />
        </label>
      )}
      {type === "shape" && (
        <label>
          Shape kind
          <select value={shapeKind} onChange={(e) => setShapeKind(e.target.value)}>
            {SHAPE_KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {kind}
              </option>
            ))}
          </select>
        </label>
      )}
      {(type === "reportifyr" || type === "quarto") && (
        <label>
          {type === "reportifyr" ? "Reportifyr artifact" : "Quarto fragment (.qmd)"}
          <select
            value={source}
            onChange={(e) => setSource(e.target.value)}
            disabled={!projectFiles}
          >
            {(projectFiles ?? []).length === 0 && <option value="">No candidates found</option>}
            {(projectFiles ?? []).map((file) => (
              <option key={file} value={file}>
                {file}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="element-list__add-form-actions">
        <button
          type="submit"
          disabled={busy || !id.trim() || existingIds.has(id.trim())}
        >
          {busy ? "Adding…" : "Add"}
        </button>
        <button type="button" onClick={onDone} disabled={busy}>
          Cancel
        </button>
      </div>
      {existingIds.has(id.trim()) && (
        <p className="element-list__error" role="alert">
          an element with this id already exists
        </p>
      )}
      {error && (
        <p className="element-list__error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

function FurnitureRow({
  label,
  elementId,
  active,
  extraControls,
  hint,
  busy,
  onAdd,
  onRemove,
  addDisabled,
  selectable = true,
}: {
  label: string;
  elementId: string;
  active: boolean;
  extraControls?: ReactNode;
  /** Visible status/preview text (e.g. `will show "draft"`) -- not a
   * `title` tooltip, since a real user needs to see this without
   * hovering to know what Add is about to do (or why it's disabled). */
  hint?: ReactNode;
  busy: boolean;
  onAdd: () => void;
  onRemove: () => void;
  addDisabled?: boolean;
  /** `false` only for Background, which has no Add/Remove of its own
   * (spec section 7.8 -- it always fills the slide, edited only via
   * `slide.background_image` on the Config tab) and so is never a
   * selectable canvas element either. */
  selectable?: boolean;
}) {
  const { state, dispatch } = useAppContext();
  const isSelected = active && state.selectedElementId === elementId;
  return (
    <li className="element-list__item">
      <div className="element-list__row">
        <button
          type="button"
          className={isSelected ? "element-list__label element-list__label--active" : "element-list__label"}
          disabled={!active || !selectable}
          onClick={() => dispatch({ type: "SELECT_ELEMENT", elementId })}
        >
          {label}
        </button>
        {selectable && (
          <span className="element-list__row-actions">
            {active && extraControls}
            {active ? (
              <button type="button" disabled={busy} onClick={onRemove}>
                Remove
              </button>
            ) : (
              <button type="button" disabled={busy || addDisabled} onClick={onAdd}>
                Add
              </button>
            )}
          </span>
        )}
      </div>
      {hint && <p className="element-list__hint">{hint}</p>}
    </li>
  );
}

export default function ElementList({ plan, onStatusIndicatorChanged }: Props) {
  const { state, dispatch } = useAppContext();
  const { slides, layouts, furnitureSlide } = plan;
  const [addOpen, setAddOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [statusIndicator, setStatusIndicator] = useState<string | null>(null);
  const [deckStatusText, setDeckStatusText] = useState<string | null>(null);
  const [watermarkResolvedText, setWatermarkResolvedText] = useState<string | null>(null);

  const isFurnitureSlideSelected =
    furnitureSlide !== null && state.selectedSlideId === furnitureSlide.id;
  const isLayoutsMode = !isFurnitureSlideSelected && state.editorMode === "layouts";
  const slide = isFurnitureSlideSelected
    ? furnitureSlide
    : isLayoutsMode
      ? (layouts?.find((l) => l.id === state.selectedSlideId) ?? layouts?.[0])
      : (slides?.find((s) => s.id === state.selectedSlideId) ?? slides?.[0]);

  useEffect(() => {
    if (!isFurnitureSlideSelected) return;
    let cancelled = false;
    getConfig("presentation")
      .then((data) => {
        if (cancelled) return;
        const indicator = typeof data.status_indicator === "string" ? data.status_indicator : null;
        setStatusIndicator(indicator);
        const metadata = data.metadata as Record<string, unknown> | undefined;
        const watermarkOverride =
          typeof data.watermark === "string" && data.watermark !== "" ? data.watermark : null;
        const deckStatus = typeof metadata?.status === "string" ? metadata.status : null;
        setDeckStatusText(deckStatus);
        setWatermarkResolvedText(watermarkOverride ?? deckStatus);
      })
      .catch(() => {
        // Non-fatal -- the Status row just falls back to its own "add" state.
      });
    return () => {
      cancelled = true;
    };
  }, [isFurnitureSlideSelected, furnitureSlide]);

  if (!slide) {
    return <aside className="element-list element-list--empty">No slide selected.</aside>;
  }

  async function addFurniture(elementId: string) {
    setBusyId(elementId);
    setError(null);
    try {
      await addFurnitureElement(elementId);
      await plan.refetch();
      if (elementId === FURNITURE_STATUS_ID) onStatusIndicatorChanged?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  async function removeFurniture(elementId: string) {
    setBusyId(elementId);
    setError(null);
    try {
      await removeFurnitureElement(elementId);
      await plan.refetch();
      if (elementId === FURNITURE_STATUS_ID) onStatusIndicatorChanged?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  async function addElement(body: NewElementBody) {
    await plan.addElement(slide!.id, body);
  }

  async function removeElement(elementId: string) {
    setBusyId(elementId);
    setError(null);
    try {
      await plan.removeElement(slide!.id, elementId);
      if (state.selectedElementId === elementId) {
        dispatch({ type: "SELECT_ELEMENT", elementId: null });
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  if (isFurnitureSlideSelected) {
    const presentIds = new Set(slide.elements.map((el) => el.id));
    const statusActive = presentIds.has(FURNITURE_STATUS_ID);
    const previewIsWatermark =
      statusIndicator === null || statusIndicator === "none" || statusIndicator === "watermark";
    const previewText = previewIsWatermark ? watermarkResolvedText : deckStatusText;
    const selectedElement = findElement(slide, state.selectedElementId);

    return (
      <aside className="element-list">
        <h3>Furniture</h3>
        {error && (
          <p className="element-list__error" role="alert">
            {error}
          </p>
        )}
        <ul>
          <FurnitureRow
            label="Background"
            elementId={FURNITURE_BACKGROUND_ID}
            active={false}
            selectable={false}
            busy={false}
            onAdd={() => {}}
            onRemove={() => {}}
            hint={`${presentIds.has(FURNITURE_BACKGROUND_ID) ? "set" : "not set"} -- edit via Config tab`}
          />
          <FurnitureRow
            label="Status"
            elementId={FURNITURE_STATUS_ID}
            active={statusActive}
            busy={busyId === FURNITURE_STATUS_ID}
            onAdd={() => void addFurniture(FURNITURE_STATUS_ID)}
            onRemove={() => void removeFurniture(FURNITURE_STATUS_ID)}
            addDisabled={!previewText}
            hint={
              statusActive
                ? `configured${previewText ? ` ("${previewText}")` : ""}`
                : previewText
                  ? `will show "${previewText}"`
                  : "set Deck status above first -- nothing to show yet"
            }
            extraControls={statusIndicator === "watermark" ? <StatusHideToggle /> : undefined}
          />
          <FurnitureRow
            label="Branding"
            elementId={FURNITURE_BRANDING_ID}
            active={presentIds.has(FURNITURE_BRANDING_ID)}
            busy={busyId === FURNITURE_BRANDING_ID}
            onAdd={() => void addFurniture(FURNITURE_BRANDING_ID)}
            onRemove={() => void removeFurniture(FURNITURE_BRANDING_ID)}
          />
          <FurnitureRow
            label="Page number"
            elementId={FURNITURE_PAGE_NUMBER_ID}
            active={presentIds.has(FURNITURE_PAGE_NUMBER_ID)}
            busy={busyId === FURNITURE_PAGE_NUMBER_ID}
            onAdd={() => void addFurniture(FURNITURE_PAGE_NUMBER_ID)}
            onRemove={() => void removeFurniture(FURNITURE_PAGE_NUMBER_ID)}
          />
        </ul>
        {selectedElement && (
          <div className="element-list__expanded">
            <ElementInspector plan={plan} />
          </div>
        )}
      </aside>
    );
  }

  const visibleElements = slide.elements.filter((el) => !isFurnitureElement(el));
  // A furniture element selected via a canvas click (it can render on
  // top of an ordinary slide/layout when "Show furniture" is on) has no
  // row of its own here -- `visibleElements` deliberately excludes
  // furniture, the same reason `SlideList`'s own count does. Without
  // this, selecting one on the canvas would just show nothing here
  // instead of `ElementInspector`'s own "not part of this slide, select
  // the Furniture entry to edit it" note -- a real regression caught by
  // actually clicking through this, not anticipated up front.
  const selectedFurnitureOverlay = findElement(slide, state.selectedElementId);
  const showFurnitureOverlayInspector =
    selectedFurnitureOverlay !== undefined && isFurnitureElement(selectedFurnitureOverlay);

  return (
    <aside className="element-list">
      <h3>Elements</h3>
      {error && (
        <p className="element-list__error" role="alert">
          {error}
        </p>
      )}
      <ul>
        {visibleElements.map((el) => {
          const isSelected = state.selectedElementId === el.id;
          return (
            <li key={el.id} className="element-list__item">
              <div className="element-list__row">
                <button
                  type="button"
                  className={
                    isSelected
                      ? "element-list__label element-list__label--active"
                      : "element-list__label"
                  }
                  onClick={() => dispatch({ type: "SELECT_ELEMENT", elementId: el.id })}
                >
                  {el.type}: {el.id}
                </button>
                <button
                  type="button"
                  className="element-list__remove"
                  disabled={busyId === el.id}
                  onClick={() => void removeElement(el.id)}
                >
                  Remove
                </button>
              </div>
              {isSelected && (
                <div className="element-list__expanded">
                  <ElementInspector plan={plan} />
                </div>
              )}
            </li>
          );
        })}
        {visibleElements.length === 0 && (
          <li className="element-list__empty">No elements yet.</li>
        )}
      </ul>
      {showFurnitureOverlayInspector && (
        <div className="element-list__expanded">
          <ElementInspector plan={plan} />
        </div>
      )}
      {addOpen ? (
        <AddElementForm
          slide={slide}
          isLayoutsMode={isLayoutsMode}
          onAdd={addElement}
          onDone={() => setAddOpen(false)}
        />
      ) : (
        <button type="button" className="element-list__add-button" onClick={() => setAddOpen(true)}>
          + Add element
        </button>
      )}
    </aside>
  );
}
