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
}

export interface ProjectInfo {
  root: string;
  presentation: string;
  design: string;
  layouts: string;
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
  [key: string]: unknown;
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
