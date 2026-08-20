import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import OutputPathBrowser from "./OutputPathBrowser";

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

describe("OutputPathBrowser", () => {
  it("opens to the current value's directory and lists its entries", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/project/browse?dir=build") {
        return Promise.resolve(
          jsonResponse(200, { dir: "build", dirs: ["sub"], files: ["existing.pptx"], truncated: false })
        );
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <OutputPathBrowser currentValue="build/deck.pptx" onSelect={() => {}} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Browse…" }));

    await screen.findByText("📁 sub");
    expect(screen.getByText("existing.pptx")).toBeInTheDocument();
    expect(screen.getByLabelText("Filename")).toHaveValue("deck.pptx");
  });

  it("navigates into a subdirectory on click, fetching just that level", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/project/browse?dir=") {
        return Promise.resolve(
          jsonResponse(200, { dir: "", dirs: ["build"], files: [], truncated: false })
        );
      }
      if (url === "/api/project/browse?dir=build") {
        return Promise.resolve(
          jsonResponse(200, { dir: "build", dirs: [], files: ["existing.pptx"], truncated: false })
        );
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<OutputPathBrowser currentValue="deck.pptx" onSelect={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Browse…" }));

    await screen.findByText("📁 build");
    fireEvent.click(screen.getByText("📁 build"));

    await screen.findByText("existing.pptx");
    expect(fetchMock).toHaveBeenCalledWith("/api/project/browse?dir=build", expect.anything());
  });

  it("calls onSelect with the joined path and closes on \"Use this path\"", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/project/browse?dir=") {
        return Promise.resolve(
          jsonResponse(200, { dir: "", dirs: [], files: [], truncated: false })
        );
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);
    const onSelect = vi.fn();

    render(<OutputPathBrowser currentValue="" onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: "Browse…" }));

    const filenameInput = await screen.findByLabelText("Filename");
    fireEvent.change(filenameInput, { target: { value: "renamed.pptx" } });
    fireEvent.click(screen.getByRole("button", { name: "Use this path" }));

    expect(onSelect).toHaveBeenCalledWith("renamed.pptx");
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Use this path" })).not.toBeInTheDocument()
    );
  });

  it("shows a truncation note when the listing was capped", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        jsonResponse(200, { dir: "", dirs: ["a"], files: [], truncated: true })
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<OutputPathBrowser currentValue="" onSelect={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Browse…" }));

    await screen.findByText(/Showing the first/);
  });
});
