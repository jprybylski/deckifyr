import { afterEach, describe, expect, it, vi } from "vitest";
import { useEffect } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import BuildPanel from "./BuildPanel";
import { AppProvider, useAppContext } from "../state/AppContext";

// Mirrors `SessionControls.test.tsx`'s own seed pattern -- `state.dirty`
// only changes via a dispatched `SET_DIRTY` action.
function DirtySeed({ dirty }: { dirty: boolean }) {
  const { dispatch } = useAppContext();
  useEffect(() => {
    dispatch({ type: "SET_DIRTY", dirty });
  }, [dirty, dispatch]);
  return null;
}

function renderBuildPanel(dirty: boolean) {
  return render(
    <AppProvider>
      <DirtySeed dirty={dirty} />
      <BuildPanel />
    </AppProvider>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

describe("BuildPanel dirty guard", () => {
  it("disables Build and shows an inline warning while there are unsaved edits", () => {
    renderBuildPanel(true);

    expect(screen.getByRole("button", { name: "Build" })).toBeDisabled();
    expect(screen.getByText(/Save your changes before building/)).toBeInTheDocument();
  });

  it("enables Build with no warning once everything is saved", () => {
    renderBuildPanel(false);

    expect(screen.getByRole("button", { name: "Build" })).not.toBeDisabled();
    expect(screen.queryByText(/Save your changes before building/)).not.toBeInTheDocument();
  });
});
