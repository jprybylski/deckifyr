/**
 * Covers the project-existence gate added to `App.tsx`: a `deckifyr
 * serve` started outside a real project (`GET /api/project` fails,
 * since it resolves `presentation.yaml`/`design.yaml`/`layouts.yaml`
 * unconditionally, per `app.py`'s `_project_paths()`) must render one
 * clean message instead of the full tabbed editor -- confirmed as a
 * real bug (each panel independently rendering its own copy of the
 * same fetch failure, plus `SlideCanvas` getting stuck on "Loading
 * plan…" forever) by screenshotting an unfixed build, not just
 * reasoned about.
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

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

describe("App project gate", () => {
  it("shows a single, minimal message and no editor chrome when /api/project fails", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(404, {
        code: "E_IO",
        message: "file not found: /tmp/not-a-project/presentation.yaml",
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await waitFor(() =>
      expect(
        screen.getByText("file not found: /tmp/not-a-project/presentation.yaml")
      ).toBeInTheDocument()
    );

    // Only ever one fetch: the gate must not let any editor panel go on
    // to independently call /api/plan, /api/config/*, etc. after the
    // project check itself has already failed.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/api/project", expect.anything());

    expect(screen.queryByRole("button", { name: "Editor" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Config" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Build" })).not.toBeInTheDocument();
    expect(screen.getByText(/deckifyr init/)).toBeInTheDocument();
  });

  it("renders the editor tabs once /api/project succeeds", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
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
      if (url === "/api/config/design") {
        return Promise.resolve(
          jsonResponse(200, { slide: { width: "13.333in", height: "7.5in" } })
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
    await waitFor(() => expect(screen.getByText("No slides.")).toBeInTheDocument());
  });
});
