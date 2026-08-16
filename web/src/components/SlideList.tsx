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
 * what's still known-good alongside the error, not stale garbage. */
import { useAppContext } from "../state/AppContext";
import type { UsePlanResult } from "../state/usePlan";

interface Props {
  plan: UsePlanResult;
}

export default function SlideList({ plan }: Props) {
  const { state, dispatch } = useAppContext();
  const { slides, furnitureSlide, loading, error } = plan;

  if (loading && !slides && !furnitureSlide) return <nav className="slide-list">Loading…</nav>;
  if (!slides && !furnitureSlide) {
    return error ? <nav className="slide-list slide-list__error">{error}</nav> : null;
  }

  return (
    <nav className="slide-list">
      <h3>Slides</h3>
      {error && (
        <p className="slide-list__error" role="alert">
          {error}
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
          <li key={slide.id}>
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
          </li>
        ))}
      </ul>
    </nav>
  );
}
