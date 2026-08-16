/**
 * Typed fetch wrappers for every `deckifyr.web` endpoint
 * (`inst/python/deckifyr/web/app.py`). One function per route, all
 * throwing `ApiError` on a non-2xx response so every caller handles
 * failures the same way regardless of which of the two error body
 * shapes the server actually used:
 *
 *   - `DeckifyrError`-raised failures (422/424/404/500 from the
 *     `@app.exception_handler(DeckifyrError)` handler): `{code, message}`
 *   - plain FastAPI `HTTPException`s (404 for an unknown slide/element/
 *     job/artifact id): `{detail}`
 *
 * `ApiError` normalizes both into `.message` (always a string) while
 * keeping `.code`/`.detail` around for callers that want to branch on
 * the specific shape.
 */

import type {
  ApiErrorBody,
  ConfigDocName,
  ConfigDocument,
  ElementPatchBody,
  HealthResponse,
  Job,
  JobArtifactsResponse,
  PlanResponse,
  ProjectInfo,
  ResolvedSlide,
  ValidateResponse,
  WriteResult,
} from "../types";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | undefined;
  readonly detail: string | undefined;
  readonly body: ApiErrorBody | undefined;

  constructor(status: number, body: ApiErrorBody | undefined) {
    const message = body?.message ?? body?.detail ?? `request failed with status ${status}`;
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = body?.code;
    this.detail = body?.detail;
    this.body = body;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let body: ApiErrorBody | undefined;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      body = undefined;
    }
    throw new ApiError(response.status, body);
  }

  // A 204 or empty body has nothing to parse -- every route this client
  // calls today returns JSON on success, but guard anyway rather than
  // let `response.json()` throw on an empty stream.
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export function getHealth(): Promise<HealthResponse> {
  return request("/api/health");
}

export function getProject(): Promise<ProjectInfo> {
  return request("/api/project");
}

export function getConfig(doc: ConfigDocName): Promise<ConfigDocument> {
  return request(`/api/config/${doc}`);
}

export function putConfig(doc: ConfigDocName, body: ConfigDocument): Promise<WriteResult> {
  return request(`/api/config/${doc}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function getPlan(): Promise<PlanResponse> {
  return request("/api/plan");
}

export function postValidate(): Promise<ValidateResponse> {
  return request("/api/validate", { method: "POST" });
}

export function patchElement(
  slideId: string,
  elementId: string,
  body: ElementPatchBody
): Promise<WriteResult> {
  return request(
    `/api/slides/${encodeURIComponent(slideId)}/elements/${encodeURIComponent(elementId)}`,
    { method: "PATCH", body: JSON.stringify(body) }
  );
}

/** `design.yaml`'s `furniture` block, resolved the same way a real
 * slide's elements are (spec section 7.8, issue #21) -- a synthetic
 * `ResolvedSlide` with id `"__furniture__"`, shown as its own
 * pseudo-slide entry rather than the fixed placeholder every real slide
 * still renders it as. */
export function getFurniture(): Promise<ResolvedSlide> {
  return request("/api/furniture");
}

export function patchFurnitureElement(
  elementId: string,
  body: ElementPatchBody
): Promise<WriteResult> {
  return request(`/api/furniture/elements/${encodeURIComponent(elementId)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

/** Materializes a furniture kind's `design.yaml` sub-object with a
 * sensible default box/style, if it isn't already configured (a 422 if
 * it already is) -- the "enable" half of issue #21's "enabling vs
 * editing" distinction; `removeFurnitureElement` is the other half. */
export function addFurnitureElement(elementId: string): Promise<WriteResult> {
  return request(`/api/furniture/elements/${encodeURIComponent(elementId)}`, {
    method: "POST",
  });
}

export function removeFurnitureElement(elementId: string): Promise<WriteResult> {
  return request(`/api/furniture/elements/${encodeURIComponent(elementId)}`, {
    method: "DELETE",
  });
}

export function postBuild(): Promise<{ job_id: string }> {
  return request("/api/build", { method: "POST" });
}

export function getJob(jobId: string): Promise<Job> {
  return request(`/api/jobs/${encodeURIComponent(jobId)}`);
}

export function getJobArtifacts(jobId: string): Promise<JobArtifactsResponse> {
  return request(`/api/jobs/${encodeURIComponent(jobId)}/artifacts`);
}

/** Same-origin binary download URL -- not fetched through `request()`
 * (no JSON to parse), just handed to an `<a href>` by `BuildPanel.tsx`. */
export function jobArtifactUrl(jobId: string, key: string): string {
  return `/api/jobs/${encodeURIComponent(jobId)}/artifacts/${encodeURIComponent(key)}`;
}

export function getSchema(doc: ConfigDocName): Promise<Record<string, unknown>> {
  return request(`/api/schemas/${doc}`);
}

export interface PollJobOptions {
  /** Milliseconds between polls. */
  intervalMs?: number;
  /** Total wall-clock budget before giving up and resolving with
   * whatever the last-seen job state was (still `"running"`/`"queued"`)
   * rather than polling forever -- a build that's genuinely stuck
   * (spec has no server-side timeout on its own subprocess) must not
   * spin the UI silently forever. */
  timeoutMs?: number;
  /** Injectable for tests; defaults to the real timers. */
  sleep?: (ms: number) => Promise<void>;
}

const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Poll `GET /api/jobs/{id}` until `status` is `"succeeded"`/`"failed"`,
 * or until `timeoutMs` elapses. Resolves with the last-seen `Job` either
 * way -- callers distinguish "finished" from "timed out but still
 * running" by checking `job.status` themselves (`"running"`/`"queued"`
 * after this resolves means the timeout was hit, not a terminal state). */
export async function pollJobUntilDone(
  jobId: string,
  options: PollJobOptions = {}
): Promise<Job> {
  const { intervalMs = 1000, timeoutMs = 120_000, sleep = defaultSleep } = options;
  const deadline = Date.now() + timeoutMs;

  let job = await getJob(jobId);
  while (job.status !== "succeeded" && job.status !== "failed") {
    if (Date.now() >= deadline) {
      return job;
    }
    await sleep(intervalMs);
    job = await getJob(jobId);
  }
  return job;
}
