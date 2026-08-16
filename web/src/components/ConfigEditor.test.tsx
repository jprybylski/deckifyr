import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import ConfigEditor from "./ConfigEditor";
import { AppProvider } from "../state/AppContext";

// `ConfigEditor` reads `useAppContext()` (to dispatch `SET_DIRTY` after an
// Apply, issue #24) -- every render in this file needs a real provider,
// not just the bare component, or that hook throws.
function renderConfigEditor() {
  return render(
    <AppProvider>
      <ConfigEditor />
    </AppProvider>
  );
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const DESIGN_DOC = { deckifyr: "0.1", slide: { width: "13.333in", height: "7.5in" }, colors: {} };
const DESIGN_SCHEMA = {
  type: "object",
  title: "DesignDocument",
  required: ["deckifyr"],
  properties: {
    deckifyr: { type: "string" },
    slide: {
      type: "object",
      properties: { width: { type: "string" }, height: { type: "string" } },
    },
    colors: { type: "object", additionalProperties: { type: "string" } },
  },
};

function stubFetch() {
  const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url === "/api/config/design" && method === "GET") {
      return Promise.resolve(jsonResponse(200, DESIGN_DOC));
    }
    if (url === "/api/schemas/design") {
      return Promise.resolve(jsonResponse(200, DESIGN_SCHEMA));
    }
    if (url === "/api/config/design" && method === "PUT") {
      const body = JSON.parse((init!.body as string) ?? "{}");
      return Promise.resolve(jsonResponse(200, { path: "/tmp/design.yaml", dirty: true, ...body }));
    }
    return Promise.reject(new Error(`unexpected fetch: ${url} ${method}`));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

describe("ConfigEditor", () => {
  it("defaults to the Form view, rendering a schema-driven field", async () => {
    stubFetch();
    renderConfigEditor();
    await screen.findByDisplayValue("0.1");
    expect(screen.getByText("deckifyr")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Form" })).toHaveClass(
      "config-editor__view-btn--active"
    );
  });

  it("switching to Raw shows the current value as pretty-printed JSON", async () => {
    stubFetch();
    renderConfigEditor();
    await screen.findByDisplayValue("0.1");

    fireEvent.click(screen.getByRole("button", { name: "Raw" }));

    const textarea = await screen.findByDisplayValue(/"deckifyr": "0.1"/);
    expect(textarea.tagName).toBe("TEXTAREA");
  });

  it("blocks switching back to Form while the Raw view has invalid JSON", async () => {
    stubFetch();
    renderConfigEditor();
    await screen.findByDisplayValue("0.1");
    fireEvent.click(screen.getByRole("button", { name: "Raw" }));
    const textarea = await screen.findByDisplayValue(/"deckifyr"/);

    fireEvent.change(textarea, { target: { value: "{not valid json" } });
    await screen.findByText(/invalid JSON/);

    fireEvent.click(screen.getByRole("button", { name: "Form" }));
    // Still on Raw -- the textarea (not the schema form) is still shown.
    expect(screen.getByDisplayValue("{not valid json")).toBeInTheDocument();
  });

  it("disables Apply while the Raw view has invalid JSON, and re-enables once it's valid again", async () => {
    stubFetch();
    renderConfigEditor();
    await screen.findByDisplayValue("0.1");
    fireEvent.click(screen.getByRole("button", { name: "Raw" }));
    const textarea = await screen.findByDisplayValue(/"deckifyr"/);

    fireEvent.change(textarea, { target: { value: "{not valid json" } });
    expect(screen.getByRole("button", { name: "Apply" })).toBeDisabled();

    fireEvent.change(textarea, { target: { value: '{"deckifyr": "0.1"}' } });
    expect(screen.getByRole("button", { name: "Apply" })).not.toBeDisabled();
  });

  it("applies the Form-edited value via PUT and refetches", async () => {
    const fetchMock = stubFetch();
    renderConfigEditor();
    const input = await screen.findByDisplayValue("0.1");

    fireEvent.change(input, { target: { value: "0.2" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => {
      const putCall = fetchMock.mock.calls.find((call) => call[1]?.method === "PUT");
      expect(putCall).toBeDefined();
      const body = JSON.parse((putCall![1] as RequestInit).body as string);
      expect(body.deckifyr).toBe("0.2");
    });
  });
});
