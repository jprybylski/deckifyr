/**
 * React context wrapper around `reducer.ts`'s pure `appReducer` --
 * selection, zoom, and the undo/redo history *stack* only. Plain
 * `useReducer`, no Redux/Zustand (matches this repo's low-dependency
 * ethos, CLAUDE.md).
 *
 * This context deliberately does not own the slide plan itself (the
 * fetched `/api/plan` data) or perform any network calls -- `App.tsx`
 * owns that as plain `useState`, and its `applyElementPatch`/`undo`/
 * `redo` functions read this context's `dispatch` for bookkeeping while
 * doing the actual `PATCH`/refetch themselves. Keeping IO out of this
 * module is what makes `reducer.ts` (and, by extension, most of this
 * file's own logic) testable without mocking `fetch`.
 */
import { createContext, useContext, useReducer, type Dispatch, type ReactNode } from "react";
import { appReducer, initialAppState, type AppAction, type AppState } from "./reducer";

interface AppContextValue {
  state: AppState;
  dispatch: Dispatch<AppAction>;
}

const AppContext = createContext<AppContextValue | undefined>(undefined);

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(appReducer, initialAppState);
  return <AppContext.Provider value={{ state, dispatch }}>{children}</AppContext.Provider>;
}

export function useAppContext(): AppContextValue {
  const value = useContext(AppContext);
  if (!value) {
    throw new Error("useAppContext must be used within an AppProvider");
  }
  return value;
}
