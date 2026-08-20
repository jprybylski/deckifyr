import { afterEach, describe, expect, it, vi } from "vitest";
import { useEffect } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

// Reads `state.dirty` out into visible text -- `BuildPanel` itself
// doesn't render a dirty indicator (that's `SessionControls`, a sibling
// in `App.tsx`), so this stands in for it to prove an edit here
// actually reaches the shared `AppContext`, not just this component's
// own local state.
function DirtyReadout() {
  const { state } = useAppContext();
  return <span data-testid="dirty-readout">{state.dirty ? "dirty" : "clean"}</span>;
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const PRESENTATION_DOC = {
  deckifyr: "0.1",
  build: { output: "build/deck.pptx" },
};

const AVAILABLE = {
  available: true,
  binary: "soffice",
  display_name: "LibreOffice",
  install_url: null,
};

const UNAVAILABLE = {
  available: false,
  binary: "soffice",
  display_name: "LibreOffice",
  install_url: "https://www.libreoffice.org/download/download/",
};

/** Stubs the two fetches `BuildPanel` always makes on mount
 * (`GET /api/config/presentation`, `GET /api/preview/availability`),
 * plus whatever `extra` handler a test supplies for its own job/config
 * routes. */
function stubBuildPanelFetch(
  availability: typeof AVAILABLE | typeof UNAVAILABLE = AVAILABLE,
  extra?: (url: string, init: RequestInit | undefined) => Response | undefined
) {
  const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/config/presentation" && (init?.method ?? "GET") === "GET") {
      return Promise.resolve(jsonResponse(200, PRESENTATION_DOC));
    }
    if (url === "/api/preview/availability") {
      return Promise.resolve(jsonResponse(200, availability));
    }
    const extraResponse = extra?.(url, init);
    if (extraResponse) return Promise.resolve(extraResponse);
    return Promise.reject(new Error(`unexpected fetch: ${url} ${init?.method ?? "GET"}`));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
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
  it("disables Build and shows an inline warning while there are unsaved edits", async () => {
    stubBuildPanelFetch();
    renderBuildPanel(true);
    await screen.findByDisplayValue("build/deck.pptx");

    expect(screen.getByRole("button", { name: "Build" })).toBeDisabled();
    expect(screen.getByText(/Save your changes before building/)).toBeInTheDocument();
  });

  it("enables Build with no warning once everything is saved", async () => {
    stubBuildPanelFetch();
    renderBuildPanel(false);
    await screen.findByDisplayValue("build/deck.pptx");

    expect(screen.getByRole("button", { name: "Build" })).not.toBeDisabled();
    expect(screen.queryByText(/Save your changes before building/)).not.toBeInTheDocument();
  });
});

describe("BuildPanel output path (issue #27)", () => {
  it("shows the fetched build.output and saves an edit on blur", async () => {
    let putBody: unknown;
    const fetchMock = stubBuildPanelFetch(AVAILABLE, (url, init) => {
      if (url === "/api/config/presentation" && init?.method === "PUT") {
        putBody = JSON.parse(init.body as string);
        return jsonResponse(200, { path: "presentation.yaml", dirty: true });
      }
      return undefined;
    });
    renderBuildPanel(false);

    const input = await screen.findByDisplayValue("build/deck.pptx");
    fireEvent.blur(input, { target: { value: "build/renamed.pptx" } });

    await waitFor(() =>
      expect(putBody).toMatchObject({ build: { output: "build/renamed.pptx" } })
    );
    expect(fetchMock).toHaveBeenCalled();
  });

  it("marks the shared app state dirty after a successful save", async () => {
    stubBuildPanelFetch(AVAILABLE, (url, init) => {
      if (url === "/api/config/presentation" && init?.method === "PUT") {
        return jsonResponse(200, { path: "presentation.yaml", dirty: true });
      }
      return undefined;
    });
    render(
      <AppProvider>
        <DirtyReadout />
        <BuildPanel />
      </AppProvider>
    );

    const input = await screen.findByDisplayValue("build/deck.pptx");
    expect(screen.getByTestId("dirty-readout")).toHaveTextContent("clean");
    fireEvent.blur(input, { target: { value: "build/renamed.pptx" } });

    await waitFor(() => expect(screen.getByTestId("dirty-readout")).toHaveTextContent("dirty"));
  });
});

describe("BuildPanel previews checkbox (issue #32)", () => {
  it("reflects build.previews and PUTs an edit when toggled", async () => {
    let putBody: unknown;
    stubBuildPanelFetch(AVAILABLE, (url, init) => {
      if (url === "/api/config/presentation" && init?.method === "PUT") {
        putBody = JSON.parse(init.body as string);
        return jsonResponse(200, { path: "presentation.yaml", dirty: true });
      }
      return undefined;
    });
    renderBuildPanel(false);

    await screen.findByDisplayValue("build/deck.pptx");
    const checkbox = screen.getByRole("checkbox", {
      name: "Render slide previews (PNG + PDF) with this build",
    });
    expect(checkbox).not.toBeChecked();

    fireEvent.click(checkbox);

    await waitFor(() => expect(putBody).toMatchObject({ build: { previews: true } }));
  });

  it("starts checked when build.previews is already true", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/config/presentation" && (init?.method ?? "GET") === "GET") {
        return Promise.resolve(
          jsonResponse(200, { deckifyr: "0.1", build: { output: "build/deck.pptx", previews: true } })
        );
      }
      if (url === "/api/preview/availability") {
        return Promise.resolve(jsonResponse(200, AVAILABLE));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);
    renderBuildPanel(false);

    await screen.findByDisplayValue("build/deck.pptx");
    expect(
      screen.getByRole("checkbox", { name: "Render slide previews (PNG + PDF) with this build" })
    ).toBeChecked();
  });
});

describe("BuildPanel build result gallery (issue #32)", () => {
  it("renders a PreviewGallery for the build job's own preview-N/pdf artifacts", async () => {
    stubBuildPanelFetch(AVAILABLE, (url, init) => {
      if (url === "/api/build" && init?.method === "POST") {
        return jsonResponse(200, { job_id: "build-job-1" });
      }
      if (url === "/api/jobs/build-job-1") {
        return jsonResponse(200, {
          id: "build-job-1",
          status: "succeeded",
          result: { output: "build/deck.pptx", previews: ["a.png"], preview_pdf: "a.pdf" },
          error: null,
        });
      }
      if (url === "/api/jobs/build-job-1/artifacts") {
        return jsonResponse(200, { artifacts: ["pptx", "preview-0", "pdf"] });
      }
      return undefined;
    });
    renderBuildPanel(false);
    await screen.findByDisplayValue("build/deck.pptx");

    fireEvent.click(screen.getByRole("button", { name: "Build" }));

    await waitFor(() => expect(screen.getByRole("img", { name: "preview-0" })).toBeInTheDocument());
    // The generic artifact-link list keeps non-preview artifacts only --
    // the gallery already presents preview-0/pdf.
    expect(screen.getByRole("link", { name: "pptx" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "preview-0" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "pdf" })).not.toBeInTheDocument();
  });
});

describe("BuildPanel preview availability (issue #27)", () => {
  it("shows an install link and disables Preview when LibreOffice isn't available", async () => {
    stubBuildPanelFetch(UNAVAILABLE);
    renderBuildPanel(false);

    await screen.findByText(/isn.t installed/);
    expect(screen.getByRole("link", { name: /Install LibreOffice/ })).toHaveAttribute(
      "href",
      "https://www.libreoffice.org/download/download/"
    );
    expect(screen.getByRole("button", { name: "Preview" })).toBeDisabled();
  });

  it("leaves Preview enabled with no warning when LibreOffice is available", async () => {
    stubBuildPanelFetch(AVAILABLE);
    renderBuildPanel(false);

    await screen.findByDisplayValue("build/deck.pptx");
    expect(screen.queryByText(/isn.t installed/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview" })).not.toBeDisabled();
  });
});

describe("BuildPanel preview job (issue #27)", () => {
  it("shows a progress bar while queued, then the preview images and PDF viewer", async () => {
    // Resolves "succeeded" on the very first poll -- `pollJobUntilDone`'s
    // own interval/timeout/multi-poll behavior is already covered at the
    // pure-function level in `api/client.test.ts`; this only needs to
    // confirm BuildPanel renders correctly once a job finishes.
    stubBuildPanelFetch(AVAILABLE, (url, init) => {
      if (url === "/api/preview" && init?.method === "POST") {
        return jsonResponse(200, { job_id: "job-1" });
      }
      if (url === "/api/jobs/job-1") {
        return jsonResponse(200, {
          id: "job-1",
          status: "succeeded",
          result: { previews: ["a.png"], preview_pdf: "a.pdf" },
          error: null,
        });
      }
      if (url === "/api/jobs/job-1/artifacts") {
        return jsonResponse(200, { artifacts: ["pptx", "preview-0", "pdf"] });
      }
      return undefined;
    });
    renderBuildPanel(false);
    await screen.findByDisplayValue("build/deck.pptx");

    act(() => {
      screen.getByRole("button", { name: "Preview" }).click();
    });
    expect(screen.getByRole("progressbar")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByRole("img", { name: "preview-0" })).toBeInTheDocument());
    // The PDF is minimized by default (issue #32) -- only requesting it
    // explicitly mounts the iframe.
    expect(screen.queryByTitle("Preview PDF")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Show PDF preview"));
    expect(screen.getByTitle("Preview PDF")).toHaveAttribute(
      "src",
      "/api/jobs/job-1/artifacts/pdf"
    );
  });

  it("surfaces a missing-dependency error from a failed job", async () => {
    stubBuildPanelFetch(AVAILABLE, (url, init) => {
      if (url === "/api/preview" && init?.method === "POST") {
        return jsonResponse(200, { job_id: "job-2" });
      }
      if (url === "/api/jobs/job-2") {
        return jsonResponse(200, {
          id: "job-2",
          status: "failed",
          result: null,
          error: {
            code: "E_MISSING_DEPENDENCY",
            message: "soffice not found",
            dependency: {
              name: "soffice",
              display_name: "LibreOffice",
              install_url: "https://www.libreoffice.org/download/download/",
            },
          },
        });
      }
      if (url === "/api/jobs/job-2/artifacts") {
        return jsonResponse(200, { artifacts: [] });
      }
      return undefined;
    });
    renderBuildPanel(false);
    await screen.findByDisplayValue("build/deck.pptx");

    await act(async () => {
      screen.getByRole("button", { name: "Preview" }).click();
    });

    await waitFor(() =>
      expect(screen.getAllByRole("link", { name: /Install LibreOffice/ }).length).toBeGreaterThan(
        0
      )
    );
  });
});
