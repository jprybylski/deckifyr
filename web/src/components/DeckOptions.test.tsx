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
      // Selecting any placement other than "none" also auto-configures a
      // default style (`selectStatusIndicator`'s own docstring) --
      // stubbed here so that follow-up call succeeds harmlessly; its own
      // behavior is covered by the dedicated auto-configure tests below.
      if (url === "/api/furniture/elements/__furniture_status" && init?.method === "POST") {
        return Promise.resolve(jsonResponse(200, { element: "__furniture_status" }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DeckOptions />);

    const select = await screen.findByLabelText("Status indicator");
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

  it("auto-configures a default style right after selecting a fresh placement", async () => {
    // Regression: picking a placement the dropdown itself presents as a
    // normal, always-selectable option used to immediately 422 the real
    // slide canvas ("furniture.status has no 'corner_tl' configured"),
    // which reads as the editor locking up on an ordinary action, not a
    // deliberate strictness policy. Selecting now also materializes a
    // default style in the same action, so there's never a moment where
    // status_indicator points at something unconfigured.
    const presentation = { deckifyr: "0.1", status_indicator: "none", watermark: null, slides: [] };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/api/config/presentation" && method === "PUT") {
        return Promise.resolve(jsonResponse(200, { path: "/tmp/presentation.yaml" }));
      }
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, presentation));
      }
      if (url === "/api/furniture/elements/__furniture_status" && method === "POST") {
        return Promise.resolve(jsonResponse(200, { element: "__furniture_status" }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url} ${method}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DeckOptions />);

    const select = await screen.findByLabelText("Status indicator");
    fireEvent.change(select, { target: { value: "corner-tl" } });

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          (call) =>
            String(call[0]) === "/api/furniture/elements/__furniture_status" &&
            call[1]?.method === "POST"
        )
      ).toBe(true);
    });
  });

  it("selecting None never tries to auto-configure a style", async () => {
    const presentation = { deckifyr: "0.1", status_indicator: "watermark", watermark: null, slides: [] };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/api/config/presentation" && method === "PUT") {
        return Promise.resolve(jsonResponse(200, { path: "/tmp/presentation.yaml" }));
      }
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, presentation));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url} ${method}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DeckOptions />);

    const select = await screen.findByLabelText("Status indicator");
    fireEvent.change(select, { target: { value: "none" } });

    await waitFor(() => {
      expect(fetchMock.mock.calls.some((call) => call[1]?.method === "PUT")).toBe(true);
    });
    expect(
      fetchMock.mock.calls.some((call) => String(call[0]).includes("/api/furniture/"))
    ).toBe(false);
  });

  it("swallows an 'already configured' 422 from the auto-configure step without showing an error", async () => {
    const presentation = { deckifyr: "0.1", status_indicator: "none", watermark: null, slides: [] };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/api/config/presentation" && method === "PUT") {
        return Promise.resolve(jsonResponse(200, { path: "/tmp/presentation.yaml" }));
      }
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, presentation));
      }
      if (url === "/api/furniture/elements/__furniture_status" && method === "POST") {
        return Promise.resolve(
          jsonResponse(422, {
            code: "E_SCHEMA_VALIDATION",
            message: "design.yaml's furniture.status.corner_tl is already configured",
          })
        );
      }
      return Promise.reject(new Error(`unexpected fetch: ${url} ${method}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DeckOptions />);

    const select = await screen.findByLabelText("Status indicator");
    fireEvent.change(select, { target: { value: "corner-tl" } });

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          (call) =>
            String(call[0]) === "/api/furniture/elements/__furniture_status" &&
            call[1]?.method === "POST"
        )
      ).toBe(true);
    });
    expect(screen.queryByText(/already configured/)).not.toBeInTheDocument();
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

    const select = await screen.findByLabelText("Status indicator");
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

  it("keeps Watermark override visible for a corner placement, but it's inert there", async () => {
    // Regression: an earlier version of this fix hid the field entirely
    // whenever a corner was selected -- which then hid the one field
    // needed to set it up *before* switching to the watermark placement.
    // It stays visible and editable always; only the *precedence warning*
    // (below) is placement-specific.
    const presentation = {
      deckifyr: "0.1",
      status_indicator: "corner-tl",
      metadata: { title: "Q3 Review", status: "demo" },
      watermark: null,
      slides: [],
    };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, presentation));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DeckOptions />);

    await screen.findByLabelText("Watermark override");
  });

  it("warns that the override replaces Deck status only once both are set on the watermark placement", async () => {
    // Regression: a real user set Deck status ("demo") and Watermark
    // override ("test") together while status_indicator was "watermark",
    // and only discovered the override wins (not additive) after adding
    // it and finding different text than expected.
    const presentation = {
      deckifyr: "0.1",
      status_indicator: "watermark",
      metadata: { title: "Q3 Review", status: "demo" },
      watermark: null,
      slides: [],
    };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/config/presentation" && init?.method === "PUT") {
        return Promise.resolve(jsonResponse(200, { path: "/tmp/presentation.yaml", dirty: true }));
      }
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, presentation));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DeckOptions />);

    const input = await screen.findByLabelText("Watermark override");
    // No override text yet -- no warning.
    expect(screen.queryByText(/replaces Deck status/)).not.toBeInTheDocument();

    fireEvent.blur(input, { target: { value: "test" } });

    await waitFor(() => expect(screen.getByText(/replaces Deck status/)).toBeInTheDocument());
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

    const select = await screen.findByLabelText("Status indicator");
    fireEvent.change(select, { target: { value: "watermark" } });

    await waitFor(() => expect(screen.getByText("no")).toBeInTheDocument());
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("checking Show watermark auto-configures a default style, mirroring the dropdown", async () => {
    // The actual reported requirement: a watermark and a corner status
    // indicator must be independently activatable -- this checkbox is
    // the watermark's own additive on/off switch, separate from Status
    // indicator entirely, so it must work the same while a corner is
    // already selected.
    const presentation = {
      deckifyr: "0.1",
      status_indicator: "corner-tl",
      watermark_overlay: false,
      metadata: { status: "demo" },
      slides: [],
    };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/api/config/presentation" && method === "PUT") {
        return Promise.resolve(jsonResponse(200, { path: "/tmp/presentation.yaml" }));
      }
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, presentation));
      }
      if (url === "/api/furniture/elements/__furniture_watermark" && method === "POST") {
        return Promise.resolve(jsonResponse(200, { element: "__furniture_watermark" }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url} ${method}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DeckOptions />);

    const checkbox = await screen.findByLabelText("Show watermark");
    expect(checkbox).not.toBeChecked();
    fireEvent.click(checkbox);

    await waitFor(() => {
      const putCall = fetchMock.mock.calls.find((call) => call[1]?.method === "PUT");
      expect(putCall).toBeDefined();
      const body = JSON.parse((putCall![1] as RequestInit).body as string);
      expect(body.watermark_overlay).toBe(true);
      // status_indicator is untouched -- the corner stays selected.
      expect(body.status_indicator).toBe("corner-tl");
    });
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          (call) =>
            String(call[0]) === "/api/furniture/elements/__furniture_watermark" &&
            call[1]?.method === "POST"
        )
      ).toBe(true);
    });
  });

  it("unchecking Show watermark only flips the flag, without deleting the design.yaml style", async () => {
    const presentation = {
      deckifyr: "0.1",
      status_indicator: "corner-tl",
      watermark_overlay: true,
      metadata: { status: "demo" },
      slides: [],
    };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/api/config/presentation" && method === "PUT") {
        return Promise.resolve(jsonResponse(200, { path: "/tmp/presentation.yaml" }));
      }
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, presentation));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url} ${method}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DeckOptions />);

    const checkbox = await screen.findByLabelText("Show watermark");
    expect(checkbox).toBeChecked();
    fireEvent.click(checkbox);

    await waitFor(() => {
      const putCall = fetchMock.mock.calls.find((call) => call[1]?.method === "PUT");
      expect(putCall).toBeDefined();
      const body = JSON.parse((putCall![1] as RequestInit).body as string);
      expect(body.watermark_overlay).toBe(false);
    });
    // No furniture route touched -- unchecking never deletes the style.
    expect(
      fetchMock.mock.calls.some((call) => String(call[0]).includes("/api/furniture/"))
    ).toBe(false);
  });

  it("shows the watermark-precedence warning whenever the watermark is active, not just in watermark mode", async () => {
    const presentation = {
      deckifyr: "0.1",
      status_indicator: "corner-tl",
      watermark_overlay: true,
      watermark: "test",
      metadata: { status: "demo" },
      slides: [],
    };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/config/presentation") {
        return Promise.resolve(jsonResponse(200, presentation));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DeckOptions />);

    await screen.findByLabelText("Watermark override");
    await screen.findByText(/replaces Deck status/);
  });
});
