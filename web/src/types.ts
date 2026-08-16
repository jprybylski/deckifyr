// Mirrors `inst/python/deckifyr/web/app.py`'s JSON contract exactly --
// this is the one place the frontend's understanding of that contract
// lives, so a shape change in `_serialize_element`/`_serialize_slide`
// only needs updating here.

export type ElementType =
  | "text"
  | "markdown"
  | "image"
  | "shape"
  | "group"
  | "table"
  | "reportifyr"
  | "quarto";

/** Every box field is a formatted unit string, e.g. `"1.5000in"`
 * (`format_length` in `app.py`) -- always inches, always parseable back
 * with a trailing `"in"`. See `geometry.ts` for the parse/format pair. */
export interface ElementBox {
  x: string;
  y: string;
  width: string;
  height: string;
}

export interface ResolvedTextStyle {
  font: string;
  size_pt: number;
  bold: boolean;
  italic: boolean;
  color: string;
  opacity: number | null;
  text_transform: string | null;
}

export interface ResolvedElement {
  id: string;
  type: ElementType;
  value: unknown;
  source: string | null;
  box: ElementBox;
  rotation: number;
  z_index: number;
  order: number;
  style: ResolvedTextStyle | null;
  fit: string;
  overflow: string;
  render_mode: string;
  alt_text: string | null;
  required: boolean;
  footer_placement: string | null;
  shape_kind: string | null;
  shape_style: unknown;
  table_style: unknown;
  center: boolean;
  align: string | null;
  children: ResolvedElement[];
}

export interface ResolvedSlide {
  id: string;
  notes: string | null;
  elements: ResolvedElement[];
}

export interface PlanResponse {
  slides: ResolvedSlide[];
  /** Whether the server's in-memory working copy (issue #24's deferred-
   * save editor) currently differs from what's on disk -- `false` right
   * after load/save/discard, `true` after any mutation not yet flushed.
   * This is the one place the client seeds its own dirty indicator on
   * initial load; every mutating response also carries its own `dirty`
   * (see `WriteResult`) so the indicator stays live without polling. */
  dirty: boolean;
}

export interface ProjectInfo {
  root: string;
  presentation: string;
  design: string;
  layouts: string;
}

/** Who launched this `deckifyr serve` process -- `cli.py`'s `serve
 * --launcher` flag, default `"cli"`; `R/serve.R`'s `deck_serve()` passes
 * `"r"`. Carried on `GET /api/health` (not `/api/project`, which is
 * exactly the route that fails when there's no project to show
 * launcher-appropriate "no project found" instructions for). */
export type Launcher = "cli" | "r";

export interface HealthResponse {
  status: string;
  launcher: Launcher;
  /** Non-null only in a dev checkout whose built `web/static/` bundle is
   * older than `web/src/` (`deckifyr.web.app._frontend_build_warning`) --
   * a real trap this exists to surface instead of leaving a stale-JS
   * session to produce confusing, seemingly-random UI bugs that a
   * browser hard-refresh alone won't fix (StaticFiles really does serve
   * fresh bytes each request; they're just still the old bytes, because
   * nobody re-ran `npm run build`). Always `null` outside a source
   * checkout (an installed wheel/R package never ships `web/src`). */
  frontend_warning: string | null;
}

export type ConfigDocName = "design" | "layouts" | "presentation";

/** Raw, already-parsed YAML -- shape varies by document, so this is
 * intentionally a loose bag of fields (spec's own config documents are
 * only validated server-side; the frontend edits them as raw text, not
 * a typed form -- see `ConfigEditor.tsx`'s own module docstring). */
export type ConfigDocument = Record<string, unknown>;

export interface ValidateResponse {
  valid: boolean;
  presentation: string;
  slide_count: number;
  layout_count: number;
  schema_version: string;
}

export interface ElementPatchBody {
  box?: Partial<{ x: number; y: number; width: number; height: number }>;
  rotation?: number;
  z_index?: number;
  value?: string;
}

export interface WriteResult {
  path: string;
  /** See `PlanResponse.dirty` -- every mutating endpoint reports the
   * working copy's dirty state right after applying its own edit
   * (already `false` again if `build.autosave` is on, since the mutation
   * is flushed to disk before the response is built). */
  dirty: boolean;
  [key: string]: unknown;
}

export interface SaveResult {
  /** Which documents `POST /api/save` actually wrote -- only ones
   * touched since the last save/discard, never all three unconditionally
   * (issue #24: saving shouldn't dirty a file's mtime/git diff just
   * because *something else* in the session changed). */
  saved: ConfigDocName[];
  dirty: boolean;
}

export interface DiscardResult {
  dirty: boolean;
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed";

export interface JobResult {
  output?: string;
  manifest?: string;
  slide_count?: number;
  warning_count?: number;
  previews?: string[];
  [key: string]: unknown;
}

export interface ApiErrorBody {
  code?: string;
  message?: string;
  detail?: string;
}

export interface Job {
  id: string;
  status: JobStatus;
  result: JobResult | null;
  error: ApiErrorBody | null;
}

export interface JobArtifactsResponse {
  artifacts: string[];
}
