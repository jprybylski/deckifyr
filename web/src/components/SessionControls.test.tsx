import { afterEach, describe, expect, it, vi } from "vitest";
import { useEffect } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import SessionControls from "./SessionControls";
import { AppProvider, useAppContext } from "../state/AppContext";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// `state.dirty` only changes via a dispatched `SET_DIRTY` action --
// this seeds it before `SessionControls` itself renders, the same way a
// real mutation elsewhere in the app (a `patchElement`, an Apply in
// `ConfigEditor`) would.
function DirtySeed({ dirty }: { dirty: boolean }) {
  const { dispatch } = useAppContext();
  useEffect(() => {
    dispatch({ type: "SET_DIRTY", dirty });
  }, [dirty, dispatch]);
  return null;
}

function renderSessionControls(dirty = false) {
  return render(
    <AppProvider>
      <DirtySeed dirty={dirty} />
      <SessionControls />
    </AppProvider>
  );
}

const PRESENTATION = { deckifyr: "0.1", build: { output: "out.pptx", autosave: false } };

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

describe("SessionControls", () => {
  it("shows a clean state with Save/Discard disabled when nothing is dirty", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/config/presentation") {
          return Promise.resolve(jsonResponse(200, PRESENTATION));
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`));
      })
    );

    renderSessionControls(false);

    await screen.findByText("All changes saved");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Discard" })).toBeDisabled();
  });

  it("enables Save/Discard once dirty, and Save clears the dirty flag", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, PRESENTATION));
      }
      if (url === "/api/save" && init?.method === "POST") {
        return Promise.resolve(jsonResponse(200, { saved: ["design"], dirty: false }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSessionControls(true);

    await screen.findByText("Unsaved changes");
    const saveButton = screen.getByRole("button", { name: "Save" });
    expect(saveButton).not.toBeDisabled();

    fireEvent.click(saveButton);

    await waitFor(() => expect(screen.getByText("All changes saved")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith("/api/save", expect.objectContaining({ method: "POST" }));
  });

  it("discard reloads the page after POST /api/discard succeeds", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, PRESENTATION));
      }
      if (url === "/api/discard" && init?.method === "POST") {
        return Promise.resolve(jsonResponse(200, { dirty: false }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);
    // A real `location.reload()` synchronously fires `beforeunload`
    // before it navigates away -- reproduced here (jsdom's own mocked
    // reload does nothing on its own) so this test actually exercises
    // the race a real Playwright/Chromium run confirmed (see
    // e2e/discard.spec.ts and dirtyRef's own comment in
    // SessionControls.tsx): a `dispatch` alone only *schedules* a
    // re-render, so a `beforeunload` listener closed over the
    // pre-dispatch `state.dirty` would still see it as `true` at this
    // exact instant and fire an unnecessary confirmation dialog.
    let beforeUnloadEvent: Event | undefined;
    const reloadMock = vi.fn(() => {
      beforeUnloadEvent = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(beforeUnloadEvent);
    });
    const originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, reload: reloadMock },
    });

    renderSessionControls(true);

    fireEvent.click(await screen.findByRole("button", { name: "Discard" }));

    await waitFor(() => expect(reloadMock).toHaveBeenCalledTimes(1));
    // Regression check: the beforeunload fired *by* the reload above must
    // not have been blocked -- i.e. dirty was already false by the time
    // reload() ran, not just eventually true after a later re-render.
    expect(beforeUnloadEvent?.defaultPrevented).toBe(false);
    expect(screen.getByText("All changes saved")).toBeInTheDocument();

    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
  });

  it("reflects presentation.yaml's build.autosave and PUTs a toggle", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/config/presentation" && init?.method === "PUT") {
        const body = JSON.parse((init!.body as string) ?? "{}");
        return Promise.resolve(jsonResponse(200, { path: "/tmp/presentation.yaml", dirty: false, ...body }));
      }
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, PRESENTATION));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSessionControls(false);

    const checkbox = await screen.findByLabelText("Autosave");
    expect(checkbox).not.toBeChecked();

    fireEvent.click(checkbox);

    await waitFor(() => {
      const putCall = fetchMock.mock.calls.find((call) => call[1]?.method === "PUT");
      expect(putCall).toBeDefined();
      const body = JSON.parse((putCall![1] as RequestInit).body as string);
      expect(body.build.autosave).toBe(true);
      // Every other top-level/`build` field preserved, not dropped.
      expect(body.deckifyr).toBe("0.1");
      expect(body.build.output).toBe("out.pptx");
    });
    await waitFor(() => expect(checkbox).toBeChecked());
  });
});
