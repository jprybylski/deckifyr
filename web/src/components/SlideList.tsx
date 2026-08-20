/** Sidebar list of slides -- click to select, matching `SlideCanvas`'s
 * own `state.selectedSlideId`. A distinguished "⚙ Furniture" entry
 * (`plan.furnitureSlide`, issue #21) sits above the numbered real
 * slides/layouts -- selecting it uses the same `SELECT_SLIDE` action
 * every other entry does, `plan.furnitureSlide.id` being the sentinel
 * `FURNITURE_SLIDE_ID` (`"__furniture__"`) rather than a real
 * `presentation.yaml` slide id.
 *
 * A "Slides / Layouts" toggle (issue #30) picks which collection the
 * numbered list below the Furniture entry shows and edits --
 * `state.editorMode`, persistent across selecting individual items
 * (unlike issue #23's now-superseded per-slide Content/Layout tab).
 * "+ Add slide" becomes "+ Add layout" in Layouts mode; each row's
 * remove control is the same two-step inline confirm either way, except
 * the required `blank` layout (`deckifyr.schema.layouts.BLANK_LAYOUT_ID`)
 * has none at all -- it can never be removed. Removing a layout that's
 * still in use previews which slides would be reassigned to `blank`
 * (`plan.slideLayouts`, already fetched -- no extra request needed)
 * before the confirm is even shown; the server still rejects the
 * removal outright (422) if that reassignment would actually leave a
 * slide unbuildable, surfaced as `removeError`.
 *
 * `plan.error` (a real-slide `GET /api/plan` failure, e.g. a
 * `status_indicator` pointing at a placement `design.yaml` hasn't
 * configured yet) is shown as a banner *above* the list, not a
 * replacement of it -- a real user hit this the hard way: an earlier
 * version returned early on `error` and threw away the whole `<ul>`,
 * including the Furniture entry, which is the *one* navigation control
 * that could actually fix the problem (`GET /api/furniture` is
 * deliberately lenient about exactly this case). `slides`/`layouts`/
 * `furnitureSlide` keep whatever they last successfully fetched
 * (`usePlan.refetch`'s own `Promise.allSettled` never clears them on an
 * unrelated rejection), so this renders exactly what's still known-good
 * alongside the error, not stale garbage.
 *
 * Per-slide element counts (issue #31) exclude synthesized
 * `__furniture_*` entries -- `slide.elements` from `GET /api/plan`
 * includes them (they're merged in at plan time), so a raw
 * `.length` would count furniture as part of a slide's own content.
 * Shown as `(N)*`, the `*` explained by a `title` tooltip -- the
 * furniture pseudo-slide's own count needs no such filter, every item
 * there already *is* furniture. Layout zones never carry furniture
 * elements at all, so a layout's own count needs no filter either.
 *
 * A slide row's Remove/Duplicate controls (issue #31 follow-up
 * comments) are small, out-of-the-way icon buttons in the row's own
 * corner rather than full-width text buttons -- "obvious but out of the
 * way", per that comment's own wording. Duplicate has no confirm step
 * (non-destructive); Remove keeps the same two-step inline confirm
 * every removal in this app already uses. */
import { useEffect, useState, type FormEvent } from "react";
import { ApiError, getConfig } from "../api/client";
import { useAppContext } from "../state/AppContext";
import { isFurnitureElement } from "./SlideCanvas";
import { LAYOUT_SLIDE_PREFIX, type UsePlanResult } from "../state/usePlan";
import type { ResolvedSlide } from "../types";

interface Props {
  plan: UsePlanResult;
}

function AddSlideForm({ plan, onDone }: { plan: UsePlanResult; onDone: () => void }) {
  const [layoutNames, setLayoutNames] = useState<string[] | null>(null);
  const [id, setId] = useState("");
  const [layout, setLayout] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getConfig("layouts")
      .then((doc) => {
        if (cancelled) return;
        const layouts = (doc.layouts as Record<string, unknown> | undefined) ?? {};
        setLayoutNames(Object.keys(layouts));
      })
      .catch(() => {
        if (!cancelled) setLayoutNames([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!id.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await plan.addSlide({ id: id.trim(), layout: layout === "" ? null : layout });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="slide-list__add-form" onSubmit={(e) => void submit(e)}>
      <label>
        New slide id
        <input value={id} onChange={(e) => setId(e.target.value)} autoFocus />
      </label>
      <label>
        Layout
        <select value={layout} onChange={(e) => setLayout(e.target.value)} disabled={!layoutNames}>
          <option value="">Freeform (no layout)</option>
          {(layoutNames ?? []).map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </label>
      <div className="slide-list__add-form-actions">
        <button type="submit" disabled={busy || !id.trim()}>
          {busy ? "Adding…" : "Add"}
        </button>
        <button type="button" onClick={onDone} disabled={busy}>
          Cancel
        </button>
      </div>
      {error && (
        <p className="slide-list__error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

function AddLayoutForm({ plan, onDone }: { plan: UsePlanResult; onDone: () => void }) {
  const [id, setId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!id.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await plan.addLayout(id.trim());
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="slide-list__add-form" onSubmit={(e) => void submit(e)}>
      <label>
        New layout id
        <input value={id} onChange={(e) => setId(e.target.value)} autoFocus />
      </label>
      <div className="slide-list__add-form-actions">
        <button type="submit" disabled={busy || !id.trim()}>
          {busy ? "Adding…" : "Add"}
        </button>
        <button type="button" onClick={onDone} disabled={busy}>
          Cancel
        </button>
      </div>
      {error && (
        <p className="slide-list__error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

function elementCountLabel(item: ResolvedSlide, excludeFurniture: boolean): string {
  const count = excludeFurniture
    ? item.elements.filter((el) => !isFurnitureElement(el)).length
    : item.elements.length;
  return excludeFurniture ? `(${count})*` : `(${count})`;
}

/** `"<id>-copy"`, or `"<id>-copy-2"`/`"-3"`/... if that's already taken
 * -- issue #31 follow-up's "simple duplicate button", no naming prompt. */
function nextDuplicateId(baseId: string, existingIds: ReadonlySet<string>): string {
  let candidate = `${baseId}-copy`;
  let n = 2;
  while (existingIds.has(candidate)) {
    candidate = `${baseId}-copy-${n}`;
    n += 1;
  }
  return candidate;
}

export default function SlideList({ plan }: Props) {
  const { state, dispatch } = useAppContext();
  const { slides, layouts, furnitureSlide, slideLayouts, loading, error } = plan;
  const [addOpen, setAddOpen] = useState(false);
  const [pendingRemoveId, setPendingRemoveId] = useState<string | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);
  const [duplicateError, setDuplicateError] = useState<string | null>(null);

  const isLayoutsMode = state.editorMode === "layouts";
  const items = isLayoutsMode ? layouts : slides;

  // A pending remove confirm/error is scoped to one collection -- left
  // showing after switching Slides/Layouts (a real rough edge caught by
  // actually clicking through this, not anticipated up front), it reads
  // as a confusing leftover banner for whatever's now on screen instead
  // of the thing it was actually about.
  useEffect(() => {
    setPendingRemoveId(null);
    setRemoveError(null);
  }, [isLayoutsMode]);

  if (loading && !items && !furnitureSlide) return <nav className="slide-list">Loading…</nav>;
  if (!items && !furnitureSlide) {
    return error ? <nav className="slide-list slide-list__error">{error}</nav> : null;
  }

  async function confirmRemove(id: string) {
    setRemoveBusy(true);
    setRemoveError(null);
    try {
      if (isLayoutsMode) {
        await plan.removeLayout(id.slice(LAYOUT_SLIDE_PREFIX.length));
      } else {
        await plan.removeSlide(id);
      }
      setPendingRemoveId(null);
    } catch (err) {
      setRemoveError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setRemoveBusy(false);
    }
  }

  async function duplicate(slideId: string) {
    const existingIds = new Set((slides ?? []).map((s) => s.id));
    setDuplicateError(null);
    try {
      await plan.duplicateSlide(slideId, nextDuplicateId(slideId, existingIds));
    } catch (err) {
      setDuplicateError(err instanceof ApiError ? err.message : String(err));
    }
  }

  return (
    <nav className="slide-list">
      <div className="slide-list__mode-toggle" role="group" aria-label="Slides or layouts">
        <button
          type="button"
          className={!isLayoutsMode ? "active" : ""}
          onClick={() => dispatch({ type: "SET_EDITOR_MODE", mode: "slides" })}
        >
          Slides
        </button>
        <button
          type="button"
          className={isLayoutsMode ? "active" : ""}
          onClick={() => dispatch({ type: "SET_EDITOR_MODE", mode: "layouts" })}
        >
          Layouts
        </button>
      </div>
      {error && (
        <p className="slide-list__error" role="alert">
          {error}
        </p>
      )}
      {removeError && (
        <p className="slide-list__error" role="alert">
          {removeError}
        </p>
      )}
      {duplicateError && (
        <p className="slide-list__error" role="alert">
          {duplicateError}
        </p>
      )}
      <ul>
        {furnitureSlide && (
          <li>
            <button
              type="button"
              className={
                furnitureSlide.id === state.selectedSlideId
                  ? "slide-list__item slide-list__item--furniture slide-list__item--active"
                  : "slide-list__item slide-list__item--furniture"
              }
              onClick={() => dispatch({ type: "SELECT_SLIDE", slideId: furnitureSlide.id })}
            >
              ⚙ Furniture
              <span className="slide-list__count">{furnitureSlide.elements.length} items</span>
            </button>
          </li>
        )}
        {(items ?? []).map((item, index) => {
          const layoutName = isLayoutsMode ? item.id.slice(LAYOUT_SLIDE_PREFIX.length) : item.id;
          const isBlankLayout = isLayoutsMode && layoutName === "blank";
          const impactedSlideIds = isLayoutsMode
            ? Object.entries(slideLayouts)
                .filter(([, l]) => l === layoutName)
                .map(([slideId]) => slideId)
            : [];
          return (
            <li key={item.id} className="slide-list__row">
              <button
                type="button"
                className={
                  item.id === state.selectedSlideId
                    ? "slide-list__item slide-list__item--active"
                    : "slide-list__item"
                }
                onClick={() => dispatch({ type: "SELECT_SLIDE", slideId: item.id })}
              >
                {index + 1}. {layoutName}
                <span className="slide-list__count" title={isLayoutsMode ? undefined : "not including furniture"}>
                  {elementCountLabel(item, !isLayoutsMode)}
                </span>
              </button>
              {pendingRemoveId === item.id ? (
                <span className="slide-list__remove-confirm">
                  Remove &ldquo;{layoutName}&rdquo;?
                  {isLayoutsMode && impactedSlideIds.length > 0
                    ? ` Used by ${impactedSlideIds.join(", ")} -- these will switch to "blank".`
                    : " This can be undone with Discard until you Save."}
                  <button type="button" disabled={removeBusy} onClick={() => void confirmRemove(item.id)}>
                    Confirm
                  </button>
                  <button type="button" disabled={removeBusy} onClick={() => setPendingRemoveId(null)}>
                    Cancel
                  </button>
                </span>
              ) : (
                <span className="slide-list__row-actions">
                  {!isLayoutsMode && (
                    <button
                      type="button"
                      className="slide-list__duplicate"
                      title={`Duplicate slide "${item.id}"`}
                      onClick={() => void duplicate(item.id)}
                    >
                      ⧉
                    </button>
                  )}
                  <button
                    type="button"
                    className="slide-list__remove-x"
                    title={
                      isBlankLayout
                        ? "\"blank\" is required and can't be removed"
                        : `Remove ${isLayoutsMode ? "layout" : "slide"} "${layoutName}"`
                    }
                    disabled={isBlankLayout}
                    onClick={() => setPendingRemoveId(item.id)}
                  >
                    ×
                  </button>
                </span>
              )}
            </li>
          );
        })}
      </ul>
      {addOpen ? (
        isLayoutsMode ? (
          <AddLayoutForm plan={plan} onDone={() => setAddOpen(false)} />
        ) : (
          <AddSlideForm plan={plan} onDone={() => setAddOpen(false)} />
        )
      ) : (
        <button type="button" className="slide-list__add-button" onClick={() => setAddOpen(true)}>
          + Add {isLayoutsMode ? "layout" : "slide"}
        </button>
      )}
    </nav>
  );
}
