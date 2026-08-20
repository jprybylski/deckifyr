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
  DiscardResult,
  ElementPatchBody,
  HealthResponse,
  Job,
  JobArtifactsResponse,
  LayoutsResponse,
  NewElementBody,
  PlanResponse,
  PreviewAvailability,
  ProjectBrowseResponse,
  ProjectInfo,
  RemoveLayoutResult,
  ResolvedSlide,
  SaveResult,
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

/** Add/remove a slide (issue #23) -- thin wrappers over
 * `deckifyr.editor.add_slide`/`remove_slide` applied to the server's
 * working copy, same deferred-save semantics as every other mutation
 * here (not written to disk until Save). `layout: null` is `Slide`'s
 * own valid freeform value, not "omitted". */
export function postAddSlide(body: {
  id: string;
  layout: string | null;
  index?: number;
  after?: string;
  before?: string;
}): Promise<WriteResult> {
  return request("/api/slides", { method: "POST", body: JSON.stringify(body) });
}

export function deleteSlide(slideId: string): Promise<WriteResult> {
  return request(`/api/slides/${encodeURIComponent(slideId)}`, { method: "DELETE" });
}

/** A layout's own zones (issue #23's Content/Layout tab), resolved as
 * `ResolvedSlide`-shaped JSON the same way the furniture pseudo-slide
 * is -- see `deckifyr.web.app._resolve_layout_zone`'s own docstring for
 * why this is a dedicated resolution path rather than reusing
 * `expand_slide` the way `getFurniture` does. */
export function getLayoutZones(layoutName: string): Promise<ResolvedSlide> {
  return request(`/api/layouts/${encodeURIComponent(layoutName)}`);
}

export function patchLayoutElement(
  layoutName: string,
  elementId: string,
  body: ElementPatchBody
): Promise<WriteResult> {
  return request(
    `/api/layouts/${encodeURIComponent(layoutName)}/elements/${encodeURIComponent(elementId)}`,
    { method: "PATCH", body: JSON.stringify(body) }
  );
}

/** Every layout in `layouts.yaml`, resolved (issue #30's Layouts editor
 * mode) -- the eager list `getLayoutZones` above was originally the
 * on-demand, one-at-a-time version of. */
export function getLayouts(): Promise<LayoutsResponse> {
  return request("/api/layouts");
}

export function postAddLayout(id: string): Promise<WriteResult> {
  return request("/api/layouts", { method: "POST", body: JSON.stringify({ id }) });
}

/** Removes a layout, reassigning any slide that used it to `"blank"` --
 * rejected (422) instead if that reassignment would leave a slide
 * unbuildable (`deckifyr.web.app.remove_layout`'s own docstring). */
export function deleteLayout(layoutName: string): Promise<RemoveLayoutResult> {
  return request(`/api/layouts/${encodeURIComponent(layoutName)}`, { method: "DELETE" });
}

/** Add/remove an element on an ordinary slide or a layout's own zones
 * (issue #31) -- geometry is always a server-computed default box; drag/
 * resize afterward the same way any other element already works. */
export function addSlideElement(slideId: string, body: NewElementBody): Promise<WriteResult> {
  return request(`/api/slides/${encodeURIComponent(slideId)}/elements`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function deleteSlideElement(slideId: string, elementId: string): Promise<WriteResult> {
  return request(
    `/api/slides/${encodeURIComponent(slideId)}/elements/${encodeURIComponent(elementId)}`,
    { method: "DELETE" }
  );
}

export function addLayoutElement(layoutName: string, body: NewElementBody): Promise<WriteResult> {
  return request(`/api/layouts/${encodeURIComponent(layoutName)}/elements`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function deleteLayoutElement(layoutName: string, elementId: string): Promise<WriteResult> {
  return request(
    `/api/layouts/${encodeURIComponent(layoutName)}/elements/${encodeURIComponent(elementId)}`,
    { method: "DELETE" }
  );
}

/** Copies an existing slide's layout/elements/notes into a new slide
 * placed immediately after it (issue #31 follow-up comment's "duplicate"
 * button). */
export function duplicateSlide(slideId: string, newId: string): Promise<WriteResult> {
  return request(`/api/slides/${encodeURIComponent(slideId)}/duplicate`, {
    method: "POST",
    body: JSON.stringify({ id: newId }),
  });
}

/** Real project files a new `reportifyr`/`quarto` element could validly
 * point at (issue #31's "Add element" picker) -- `type` mirrors
 * `deckifyr.resolvers.discovery`'s two list functions. */
export function getProjectFiles(type: "reportifyr" | "quarto"): Promise<{ files: string[] }> {
  return request(`/api/project/files?type=${encodeURIComponent(type)}`);
}

/** One single level of one project-relative directory (issue #32's
 * Build-tab output-path browser) -- `dir=""` is the project root.
 * Deliberately not recursive: `OutputPathBrowser.tsx` calls this again
 * for whichever subdirectory the user actually clicks into next, rather
 * than fetching the whole project tree up front (see
 * `deckifyr.resolvers.discovery.list_project_directory`'s own docstring
 * for why -- a deep, unrelated tree like a populated `renv/library`
 * should never get walked as a whole just because this panel opened). */
export function browseProject(dir: string): Promise<ProjectBrowseResponse> {
  return request(`/api/project/browse?dir=${encodeURIComponent(dir)}`);
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
 * editing" distinction; `removeFurnitureElement` is the other half.
 *
 * `field` (status/watermark only): materialize a *specific*
 * `furniture.status.*` field (`"watermark"`, `"corner_tl"`, ...)
 * regardless of which one `status_indicator` currently selects --
 * `FurnitureControls.tsx`'s Watermark row uses this so Add stays
 * available while a corner is active, but only once a Watermark
 * override has actually been typed in (that component's own docstring
 * has the exact rule). Omitted for every other caller, which keeps
 * deriving the target from `status_indicator` as before. */
export function addFurnitureElement(elementId: string, field?: string): Promise<WriteResult> {
  const query = field ? `?field=${encodeURIComponent(field)}` : "";
  return request(`/api/furniture/elements/${encodeURIComponent(elementId)}${query}`, {
    method: "POST",
  });
}

export function removeFurnitureElement(elementId: string, field?: string): Promise<WriteResult> {
  const query = field ? `?field=${encodeURIComponent(field)}` : "";
  return request(`/api/furniture/elements/${encodeURIComponent(elementId)}${query}`, {
    method: "DELETE",
  });
}

/** Flushes the server's in-memory working copy to disk (issue #24) --
 * only the documents actually touched since the last save/discard, per
 * `SaveResult.saved`. */
export function postSave(): Promise<SaveResult> {
  return request("/api/save", { method: "POST" });
}

/** Discards every unsaved edit, reverting the working copy to what's on
 * disk (issue #24) -- the "test freely, throw it away" button. */
export function postDiscard(): Promise<DiscardResult> {
  return request("/api/discard", { method: "POST" });
}

export function postBuild(): Promise<{ job_id: string }> {
  return request("/api/build", { method: "POST" });
}

/** Proactive LibreOffice-availability check (issue #27: "with
 * information there if they don't [have the appropriate binaries]") --
 * `BuildPanel` calls this on mount so a missing `soffice` shows as an
 * inline message with an install link *before* Preview is even
 * clickable, not only as an error after a failed attempt. */
export function getPreviewAvailability(): Promise<PreviewAvailability> {
  return request("/api/preview/availability");
}

/** Renders a preview build (issue #27) -- `slides` (1-indexed) renders
 * only those slides; omitted/undefined renders every slide. Reuses the
 * same job-polling/artifact-download machinery as `postBuild` (`Job` is
 * generic across kinds) -- the `pdf` artifact key (when present) is the
 * embedded-PDF-viewer support, `preview-N` keys are per-slide PNGs. */
export function postPreview(slides?: number[]): Promise<{ job_id: string }> {
  return request("/api/preview", {
    method: "POST",
    body: JSON.stringify(slides && slides.length > 0 ? { slides } : {}),
  });
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
