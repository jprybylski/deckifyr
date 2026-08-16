/** Sidebar list of slides -- click to select, matching `SlideCanvas`'s
 * own `state.selectedSlideId`. A distinguished "⚙ Furniture" entry
 * (`plan.furnitureSlide`, issue #21) sits above the numbered real slides
 * -- selecting it uses the same `SELECT_SLIDE` action every other entry
 * does, `plan.furnitureSlide.id` being the sentinel `FURNITURE_SLIDE_ID`
 * (`"__furniture__"`) rather than a real `presentation.yaml` slide id.
 *
 * `plan.error` (a real-slide `GET /api/plan` failure, e.g. a
 * `status_indicator` pointing at a placement `design.yaml` hasn't
 * configured yet) is shown as a banner *above* the list, not a
 * replacement of it -- a real user hit this the hard way: an earlier
 * version returned early on `error` and threw away the whole `<ul>`,
 * including the Furniture entry, which is the *one* navigation control
 * that could actually fix the problem (`GET /api/furniture` is
 * deliberately lenient about exactly this case, precisely so it stays
 * reachable). Losing it meant the editor looked locked -- reachable only
 * if you happened to already be on the Furniture slide when the error
 * first appeared. `slides`/`furnitureSlide` keep whatever they last
 * successfully fetched (`usePlan.refetch`'s own `Promise.allSettled`
 * never clears them on an unrelated rejection), so this renders exactly
 * what's still known-good alongside the error, not stale garbage.
 *
 * "+ Add slide" (issue #23) opens a small inline form -- a new slide id
 * plus a layout picker (populated from `GET /api/config/layouts`'s own
 * keys, plus a "Freeform (no layout)" option mapping to `layout: null`)
 * -- so a slide is never created with no layout chosen by accident.
 * Each row's "Remove" is a two-step inline confirm rather than a native
 * `confirm()` dialog (this app has none anywhere except the unavoidable
 * `beforeunload` in `SessionControls.tsx`), explicit about the edit
 * still being reversible via Discard before it's actually Saved --
 * issue #23's own "clear warning about the permanence" ask, without
 * overstating it (it is fully reversible right up until Save). */
import { useEffect, useState, type FormEvent } from "react";
import { ApiError, getConfig } from "../api/client";
import { useAppContext } from "../state/AppContext";
import type { UsePlanResult } from "../state/usePlan";

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

export default function SlideList({ plan }: Props) {
  const { state, dispatch } = useAppContext();
  const { slides, furnitureSlide, loading, error } = plan;
  const [addOpen, setAddOpen] = useState(false);
  const [pendingRemoveId, setPendingRemoveId] = useState<string | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);

  if (loading && !slides && !furnitureSlide) return <nav className="slide-list">Loading…</nav>;
  if (!slides && !furnitureSlide) {
    return error ? <nav className="slide-list slide-list__error">{error}</nav> : null;
  }

  async function confirmRemove(slideId: string) {
    setRemoveBusy(true);
    setRemoveError(null);
    try {
      await plan.removeSlide(slideId);
      setPendingRemoveId(null);
    } catch (err) {
      setRemoveError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setRemoveBusy(false);
    }
  }

  return (
    <nav className="slide-list">
      <h3>Slides</h3>
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
        {(slides ?? []).map((slide, index) => (
          <li key={slide.id} className="slide-list__row">
            <button
              type="button"
              className={
                slide.id === state.selectedSlideId
                  ? "slide-list__item slide-list__item--active"
                  : "slide-list__item"
              }
              onClick={() => dispatch({ type: "SELECT_SLIDE", slideId: slide.id })}
            >
              {index + 1}. {slide.id}
              <span className="slide-list__count">{slide.elements.length} elements</span>
            </button>
            {pendingRemoveId === slide.id ? (
              <span className="slide-list__remove-confirm">
                Remove &ldquo;{slide.id}&rdquo;? This can be undone with Discard until you Save.
                <button
                  type="button"
                  disabled={removeBusy}
                  onClick={() => void confirmRemove(slide.id)}
                >
                  Confirm
                </button>
                <button
                  type="button"
                  disabled={removeBusy}
                  onClick={() => setPendingRemoveId(null)}
                >
                  Cancel
                </button>
              </span>
            ) : (
              <button
                type="button"
                className="slide-list__remove"
                title={`Remove slide "${slide.id}"`}
                onClick={() => setPendingRemoveId(slide.id)}
              >
                Remove
              </button>
            )}
          </li>
        ))}
      </ul>
      {addOpen ? (
        <AddSlideForm plan={plan} onDone={() => setAddOpen(false)} />
      ) : (
        <button type="button" className="slide-list__add-button" onClick={() => setAddOpen(true)}>
          + Add slide
        </button>
      )}
    </nav>
  );
}
