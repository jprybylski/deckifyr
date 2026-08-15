/** Sidebar list of slides -- click to select, matching `SlideCanvas`'s
 * own `state.selectedSlideId`. */
import { useAppContext } from "../state/AppContext";
import type { UsePlanResult } from "../state/usePlan";

interface Props {
  plan: UsePlanResult;
}

export default function SlideList({ plan }: Props) {
  const { state, dispatch } = useAppContext();
  const { slides, loading, error } = plan;

  if (loading && !slides) return <nav className="slide-list">Loading…</nav>;
  if (error) return <nav className="slide-list slide-list__error">{error}</nav>;
  if (!slides) return null;

  return (
    <nav className="slide-list">
      <h3>Slides</h3>
      <ul>
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
