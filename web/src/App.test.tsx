/**
 * Covers the project-existence gate added to `App.tsx`: a `deckifyr
 * serve` started outside a real project (`GET /api/project` fails,
 * since it resolves `presentation.yaml`/`design.yaml`/`layouts.yaml`
 * unconditionally, per `app.py`'s `_project_paths()`) must render one
 * clean message instead of the full tabbed editor -- confirmed as a
 * real bug (each panel independently rendering its own copy of the
 * same fetch failure, plus `SlideCanvas` getting stuck on "Loading
 * plan…" forever) by screenshotting an unfixed build, not just
 * reasoned about. Also covers the launcher-aware instructions on that
 * screen (`GET /api/health`'s `launcher` field): CLI users see
 * `deckifyr init`/`deckifyr serve`, R users see
 * `initialize_deck_project()`/`deck_serve()`, and an unknown launcher
 * (health fetch itself failed) falls back to showing both rather than
 * guessing wrong.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import App from "./App";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const PROJECT_NOT_FOUND_BODY = {
  code: "E_IO",
  message: "file not found: /tmp/not-a-project/presentation.yaml",
};

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

describe("App project gate", () => {
  it("shows only CLI instructions when launched via the CLI and /api/project fails", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/health") {
        return Promise.resolve(jsonResponse(200, { status: "ok", launcher: "cli" }));
      }
      if (url === "/api/project") {
        return Promise.resolve(jsonResponse(404, PROJECT_NOT_FOUND_BODY));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await waitFor(() =>
      expect(
        screen.getByText("file not found: /tmp/not-a-project/presentation.yaml")
      ).toBeInTheDocument()
    );

    // Exactly the two checks the gate itself needs -- no editor panel
    // goes on to independently call /api/plan, /api/config/*, etc.
    // after the project check has already failed.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenCalledWith("/api/health", expect.anything());
    expect(fetchMock).toHaveBeenCalledWith("/api/project", expect.anything());

    expect(screen.queryByRole("button", { name: "Editor" })).not.toBeInTheDocument();
    expect(screen.getByText(/deckifyr init/)).toBeInTheDocument();
    expect(screen.getAllByText(/deckifyr serve --project/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/initialize_deck_project/)).not.toBeInTheDocument();
    expect(screen.queryAllByText(/deck_serve\(/).length).toBe(0);
  });

  it("shows only R instructions when launched via deck_serve() and /api/project fails", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/health") {
        return Promise.resolve(jsonResponse(200, { status: "ok", launcher: "r" }));
      }
      if (url === "/api/project") {
        return Promise.resolve(jsonResponse(404, PROJECT_NOT_FOUND_BODY));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await waitFor(() =>
      expect(screen.getByText(/initialize_deck_project/)).toBeInTheDocument()
    );
    expect(screen.getAllByText(/deck_serve\(project = /).length).toBeGreaterThan(0);
    expect(screen.queryByText(/deckifyr init/)).not.toBeInTheDocument();
    expect(screen.queryAllByText(/deckifyr serve --project/).length).toBe(0);
  });

  it("shows both instruction sets when the launcher can't be determined", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/health") {
        // The server itself is unreachable/erroring for /api/health too,
        // not just "no project" -- a rarer case, but the gate must not
        // crash or silently pick a wrong launcher for it.
        return Promise.reject(new Error("network error"));
      }
      if (url === "/api/project") {
        return Promise.resolve(jsonResponse(404, PROJECT_NOT_FOUND_BODY));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await waitFor(() => expect(screen.getByText(/deckifyr init/)).toBeInTheDocument());
    expect(screen.getByText(/initialize_deck_project/)).toBeInTheDocument();
    expect(screen.getByText("Using R:")).toBeInTheDocument();
    expect(screen.getByText("Using the CLI:")).toBeInTheDocument();
  });

  it("renders the editor tabs once /api/project succeeds", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/health") {
        return Promise.resolve(jsonResponse(200, { status: "ok", launcher: "cli" }));
      }
      if (url === "/api/project") {
        return Promise.resolve(
          jsonResponse(200, {
            root: "/tmp/proj",
            presentation: "/tmp/proj/presentation.yaml",
            design: "/tmp/proj/design.yaml",
            layouts: "/tmp/proj/layouts.yaml",
          })
        );
      }
      if (url === "/api/plan") {
        return Promise.resolve(jsonResponse(200, { slides: [] }));
      }
      if (url === "/api/furniture") {
        return Promise.resolve(jsonResponse(200, { id: "__furniture__", notes: null, elements: [] }));
      }
      if (url === "/api/layouts") {
        return Promise.resolve(jsonResponse(200, { layouts: [] }));
      }
      if (url === "/api/config/design") {
        return Promise.resolve(
          jsonResponse(200, { slide: { width: "13.333in", height: "7.5in" } })
        );
      }
      if (url === "/api/config/presentation") {
        return Promise.resolve(
          jsonResponse(200, { deckifyr: "0.1", status_indicator: "none", slides: [] })
        );
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Editor" })).toBeInTheDocument()
    );
    expect(screen.getByRole("button", { name: "Config" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Build" })).toBeInTheDocument();
    // The loaded project's directory shows in the header (a directly
    // requested fix -- there was previously no indication anywhere in
    // the UI of which project a running `deckifyr serve` was bound to).
    expect(screen.getByTitle("/tmp/proj")).toHaveTextContent("/tmp/proj");
    await waitFor(() => expect(screen.getByText("No slides.")).toBeInTheDocument());
  });

  it("shows the stale-build banner when /api/health reports frontend_warning, and nothing when it's null", async () => {
    const projectFetches = (frontendWarning: string | null) =>
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/health") {
          return Promise.resolve(
            jsonResponse(200, { status: "ok", launcher: "cli", frontend_warning: frontendWarning })
          );
        }
        if (url === "/api/project") {
          return Promise.resolve(
            jsonResponse(200, {
              root: "/tmp/proj",
              presentation: "/tmp/proj/presentation.yaml",
              design: "/tmp/proj/design.yaml",
              layouts: "/tmp/proj/layouts.yaml",
            })
          );
        }
        if (url === "/api/plan") return Promise.resolve(jsonResponse(200, { slides: [] }));
        if (url === "/api/furniture") {
          return Promise.resolve(jsonResponse(200, { id: "__furniture__", notes: null, elements: [] }));
        }
        if (url === "/api/layouts") {
          return Promise.resolve(jsonResponse(200, { layouts: [] }));
        }
        if (url === "/api/config/design") {
          return Promise.resolve(jsonResponse(200, { slide: { width: "13.333in", height: "7.5in" } }));
        }
        if (url === "/api/config/presentation") {
          return Promise.resolve(
            jsonResponse(200, { deckifyr: "0.1", status_indicator: "none", slides: [] })
          );
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`));
      });

    vi.stubGlobal("fetch", projectFetches("the built frontend under web/static/ is older than web/src/"));
    const { unmount } = render(<App />);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/older than web\/src/)
    );
    unmount();
    vi.unstubAllGlobals();

    vi.stubGlobal("fetch", projectFetches(null));
    render(<App />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Editor" })).toBeInTheDocument());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
