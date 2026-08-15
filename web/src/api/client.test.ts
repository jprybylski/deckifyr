import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, getConfig, getHealth, pollJobUntilDone, putConfig } from "./client";
import type { Job } from "../types";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("request() success path", () => {
  it("GETs and parses a JSON body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await getHealth();

    expect(result).toEqual({ status: "ok" });
    expect(fetchMock).toHaveBeenCalledWith("/api/health", expect.anything());
  });

  it("GETs a config document", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { deckifyr: "0.1" }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await getConfig("design");

    expect(result).toEqual({ deckifyr: "0.1" });
    expect(fetchMock).toHaveBeenCalledWith("/api/config/design", expect.anything());
  });
});

describe("request() error path", () => {
  it("surfaces a 422 DeckifyrError-shaped body (code/message) as ApiError.message", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(422, {
        code: "E_SCHEMA_VALIDATION",
        message: "colors.primary: not a valid hex color",
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(putConfig("design", { deckifyr: "0.1" })).rejects.toMatchObject({
      status: 422,
      code: "E_SCHEMA_VALIDATION",
      message: "colors.primary: not a valid hex color",
    });
  });

  it("surfaces a plain HTTPException {detail} body as ApiError.message too", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(404, { detail: "unknown document type 'bogus'" })
    );
    vi.stubGlobal("fetch", fetchMock);

    try {
      await getConfig("design" as never);
      expect.unreachable("expected getConfig to throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(404);
      expect(apiErr.message).toBe("unknown document type 'bogus'");
      expect(apiErr.code).toBeUndefined();
    }
  });

  it("falls back to a generic message when the error body isn't JSON", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("<html>gateway error</html>", { status: 502 })
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getHealth()).rejects.toMatchObject({
      status: 502,
      message: "request failed with status 502",
    });
  });
});

describe("pollJobUntilDone", () => {
  it("polls until the job reaches a terminal status", async () => {
    const jobs: Job[] = [
      { id: "j1", status: "queued", result: null, error: null },
      { id: "j1", status: "running", result: null, error: null },
      { id: "j1", status: "succeeded", result: { warning_count: 0 }, error: null },
    ];
    let call = 0;
    const fetchMock = vi.fn().mockImplementation(() => {
      const job = jobs[Math.min(call, jobs.length - 1)];
      call += 1;
      return Promise.resolve(jsonResponse(200, job));
    });
    vi.stubGlobal("fetch", fetchMock);

    const sleep = vi.fn().mockResolvedValue(undefined);
    const result = await pollJobUntilDone("j1", { sleep });

    expect(result.status).toBe("succeeded");
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(sleep).toHaveBeenCalledTimes(2);
  });

  it("gives up after the timeout budget and returns the last-seen (still running) job", async () => {
    const runningJob: Job = { id: "j2", status: "running", result: null, error: null };
    // A fresh Response per call -- a Response body stream can only be
    // read once, so `mockResolvedValue` (the same instance every call)
    // would fail on the second poll with "Body has already been read".
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(jsonResponse(200, runningJob))
    );
    vi.stubGlobal("fetch", fetchMock);

    let now = 0;
    vi.spyOn(Date, "now").mockImplementation(() => now);
    const sleep = vi.fn().mockImplementation(async (ms: number) => {
      now += ms;
    });

    const result = await pollJobUntilDone("j2", {
      sleep,
      intervalMs: 1000,
      timeoutMs: 2500,
    });

    expect(result.status).toBe("running");
    // Bounded, not infinite: stops polling once the deadline passes
    // rather than spinning forever on a stuck job.
    expect(sleep.mock.calls.length).toBeLessThan(10);

    vi.restoreAllMocks();
  });
});
