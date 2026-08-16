/** Sidebar list of slides -- click to select, matching `SlideCanvas`'s
 * own `state.selectedSlideId`. A distinguished "⚙ Furniture" entry
 * (`plan.furnitureSlide`, issue #21) sits above the numbered real slides
 * -- selecting it uses the same `SELECT_SLIDE` action every other entry
 * does, `plan.furnitureSlide.id` being the sentinel `FURNITURE_SLIDE_ID`
 * (`"__furniture__"`) rather than a real `presentation.yaml` slide id. */
import { useAppContext } from "../state/AppContext";
import type { UsePlanResult } from "../state/usePlan";

interface Props {
  plan: UsePlanResult;
}

export default function SlideList({ plan }: Props) {
  const { state, dispatch } = useAppContext();
  const { slides, furnitureSlide, loading, error } = plan;

  if (loading && !slides) return <nav className="slide-list">Loading…</nav>;
  if (error) return <nav className="slide-list slide-list__error">{error}</nav>;
  if (!slides) return null;

  return (
    <nav className="slide-list">
      <h3>Slides</h3>
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
        {slides.map((slide, index) => (
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
