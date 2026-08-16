import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import DeckOptions from "./DeckOptions";

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

describe("DeckOptions", () => {
  it("edits metadata.status via the Deck status field, preserving other metadata keys", async () => {
    // Regression: the only editable text field used to write
    // `watermark` (labeled generically "Text"), which is confusing for
    // a corner placement (nothing there is a "watermark") and doesn't
    // cover the common case of just wanting to set the deck's status
    // once and have every placement inherit it via
    // `resolve_watermark_text`'s `watermark ?? metadata.status`
    // fallback.
    const presentation = {
      deckifyr: "0.1",
      status_indicator: "none",
      metadata: { title: "Q3 Review", status: "draft" },
      slides: [],
    };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/config/presentation" && init?.method === "PUT") {
        return Promise.resolve(jsonResponse(200, { path: "/tmp/presentation.yaml" }));
      }
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, presentation));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DeckOptions />);

    const input = await screen.findByLabelText("Deck status");
    expect((input as HTMLInputElement).value).toBe("draft");
    fireEvent.blur(input, { target: { value: "final" } });

    await waitFor(() => {
      const putCall = fetchMock.mock.calls.find((call) => call[1]?.method === "PUT");
      expect(putCall).toBeDefined();
      const body = JSON.parse((putCall![1] as RequestInit).body as string);
      expect(body.metadata).toEqual({ title: "Q3 Review", status: "final" });
      // Every other top-level field preserved too.
      expect(body.deckifyr).toBe("0.1");
    });
  });

  it("shows the current status_indicator and PUTs only the changed field back", async () => {
    const presentation = {
      deckifyr: "0.1",
      status_indicator: "none",
      watermark: null,
      slides: [],
    };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/config/presentation" && (!init || init.method === undefined)) {
        return Promise.resolve(jsonResponse(200, presentation));
      }
      if (url === "/api/config/presentation" && init?.method === "PUT") {
        return Promise.resolve(jsonResponse(200, { path: "/tmp/presentation.yaml" }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DeckOptions />);

    const select = await screen.findByLabelText("Status/watermark");
    expect((select as HTMLSelectElement).value).toBe("none");

    fireEvent.change(select, { target: { value: "watermark" } });

    await waitFor(() => {
      const putCall = fetchMock.mock.calls.find(
        (call) => call[1]?.method === "PUT"
      );
      expect(putCall).toBeDefined();
      const body = JSON.parse((putCall![1] as RequestInit).body as string);
      expect(body.status_indicator).toBe("watermark");
      // Every other field from the original document must be preserved,
      // not dropped, since PUT replaces the whole document.
      expect(body.deckifyr).toBe("0.1");
      expect(body.slides).toEqual([]);
    });
  });

  it("surfaces a rejected save as an inline error without crashing", async () => {
    const presentation = { deckifyr: "0.1", status_indicator: "none", slides: [] };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/config/presentation" && init?.method === "PUT") {
        return Promise.resolve(
          jsonResponse(422, {
            code: "E_SCHEMA_VALIDATION",
            message: "status_indicator: watermark requires watermark text or metadata.status",
          })
        );
      }
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, presentation));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DeckOptions />);

    const select = await screen.findByLabelText("Status/watermark");
    fireEvent.change(select, { target: { value: "watermark" } });

    await waitFor(() =>
      expect(
        screen.getByText(/requires watermark text or metadata\.status/)
      ).toBeInTheDocument()
    );
  });

  it("calls onSaved after a successful save, so a caller can refetch the plan", async () => {
    // Regression: a real user edited the watermark text here and the
    // furniture pseudo-slide kept showing the old word until some
    // unrelated action happened to trigger a plan refetch. This
    // component has no access to `usePlan` itself, so it must notify a
    // caller instead of just updating its own local `doc` state.
    const presentation = { deckifyr: "0.1", status_indicator: "watermark", watermark: "old", slides: [] };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/config/presentation" && init?.method === "PUT") {
        return Promise.resolve(jsonResponse(200, { path: "/tmp/presentation.yaml" }));
      }
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, presentation));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const onSaved = vi.fn();
    render(<DeckOptions onSaved={onSaved} />);

    const input = await screen.findByLabelText("Watermark override");
    fireEvent.blur(input, { target: { value: "new" } });

    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
  });

  it("does not call onSaved when the save is rejected", async () => {
    const presentation = { deckifyr: "0.1", status_indicator: "none", slides: [] };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/config/presentation" && init?.method === "PUT") {
        return Promise.resolve(jsonResponse(422, { code: "E_SCHEMA_VALIDATION", message: "no" }));
      }
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, presentation));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const onSaved = vi.fn();
    render(<DeckOptions onSaved={onSaved} />);

    const select = await screen.findByLabelText("Status/watermark");
    fireEvent.change(select, { target: { value: "watermark" } });

    await waitFor(() => expect(screen.getByText("no")).toBeInTheDocument());
    expect(onSaved).not.toHaveBeenCalled();
  });
});
