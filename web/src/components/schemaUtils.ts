/**
 * Pure helpers behind `SchemaForm.tsx` -- JSON Schema navigation
 * (`$ref`, nullable `anyOf`), union disambiguation, and the small value
 * parsers (hex colors, unit-suffixed lengths) the specialised widgets
 * share. Kept free of React so the rules are unit-testable on their own
 * (`schemaUtils.test.ts`).
 *
 * Like the form itself this is deliberately not a general JSON Schema
 * implementation: it understands exactly the shapes pydantic emits for
 * deckifyr's three document models (see `SchemaForm.tsx`'s docstring).
 */

export type JSONSchema = Record<string, unknown>;
export type Defs = Record<string, JSONSchema>;

/** Vendor annotation the Python models attach via `ColorRef`/`Length`
 * (`schema/fields.py`) -- tells the form which specialised widget a
 * plain string field wants, with no field-name guessing. */
export const WIDGET_KEY = "x-deckifyr-widget";

export function refName(schema: JSONSchema): string | null {
  return typeof schema.$ref === "string" ? schema.$ref.replace(/^#\/\$defs\//, "") : null;
}

export function resolveRef(schema: JSONSchema, defs: Defs): JSONSchema {
  let current = schema;
  for (let guard = 0; guard < 10 && typeof current.$ref === "string"; guard += 1) {
    const next = defs[refName(current) as string];
    if (!next) break;
    current = next;
  }
  return current;
}

export function isNullSchema(schema: JSONSchema): boolean {
  return schema.type === "null";
}

/** The non-null branches of an `anyOf` (empty for a non-union). */
export function nonNullBranches(schema: JSONSchema, defs: Defs): JSONSchema[] {
  if (!Array.isArray(schema.anyOf)) return [];
  return (schema.anyOf as JSONSchema[]).filter((b) => !isNullSchema(resolveRef(b, defs)));
}

export function hasNullBranch(schema: JSONSchema, defs: Defs): boolean {
  return (
    Array.isArray(schema.anyOf) &&
    (schema.anyOf as JSONSchema[]).some((b) => isNullSchema(resolveRef(b, defs)))
  );
}

/** Unwraps pydantic's `X | None` shape. `inner` is the single non-null
 * branch, a synthetic `{anyOf: [...]}` when several remain (a real union
 * that is also optional, e.g. `str | Gradient | None`), or `null` when
 * nothing but null is left. A non-union passes through unchanged. */
export function unwrapNullable(
  schema: JSONSchema,
  defs: Defs
): { inner: JSONSchema | null; nullable: boolean } {
  if (!Array.isArray(schema.anyOf)) return { inner: schema, nullable: false };
  const branches = nonNullBranches(schema, defs);
  const nullable = hasNullBranch(schema, defs);
  if (branches.length === 0) return { inner: null, nullable };
  if (branches.length === 1) return { inner: branches[0], nullable };
  return { inner: { anyOf: branches }, nullable };
}

export type JsonType = "string" | "number" | "boolean" | "array" | "object" | "unknown";

/** The JSON type a (non-union) schema describes -- what lets a union's
 * branches be told apart by looking at the value alone. */
export function jsonTypeOf(schema: JSONSchema, defs: Defs): JsonType {
  const r = resolveRef(schema, defs);
  if (Array.isArray(r.enum)) return "string";
  switch (r.type) {
    case "string":
      return "string";
    case "number":
    case "integer":
      return "number";
    case "boolean":
      return "boolean";
    case "array":
      return "array";
    case "object":
      return "object";
    default:
      return "unknown";
  }
}

export function valueJsonType(value: unknown): JsonType {
  if (typeof value === "string") return "string";
  if (typeof value === "number") return "number";
  if (typeof value === "boolean") return "boolean";
  if (Array.isArray(value)) return "array";
  if (value !== null && typeof value === "object") return "object";
  return "unknown";
}

/** True when every branch has a distinct, known JSON type, so the
 * active branch can be inferred from the value. Two object branches (or
 * an unmodelled one) are not distinguishable -- the caller falls back to
 * raw JSON for those. */
export function branchesAreDistinguishable(branches: JSONSchema[], defs: Defs): boolean {
  const types = branches.map((b) => jsonTypeOf(b, defs));
  return !types.includes("unknown") && new Set(types).size === types.length;
}

export function activeBranchIndex(branches: JSONSchema[], defs: Defs, value: unknown): number {
  const type = valueJsonType(value);
  const index = branches.findIndex((b) => jsonTypeOf(b, defs) === type);
  return index === -1 ? 0 : index;
}

const UNION_LABELS: Record<string, string> = {
  ColorDerivation: "Derived",
  Gradient: "Gradient",
};

function humanize(name: string): string {
  return name.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/_/g, " ");
}

/** Short segmented-control label for one branch of a union. */
export function branchLabel(branch: JSONSchema, defs: Defs): string {
  const name = refName(branch);
  if (name && UNION_LABELS[name]) return UNION_LABELS[name];
  const r = resolveRef(branch, defs);
  if (r[WIDGET_KEY] === "color") return "Color";
  if (r[WIDGET_KEY] === "length") return "Length";
  switch (jsonTypeOf(branch, defs)) {
    case "string":
      return Array.isArray(r.enum) ? "Choice" : "Text";
    case "number":
      return "Number";
    case "boolean":
      return "Yes / no";
    case "array":
      return "List";
    case "object":
      return r.properties ? humanize(name ?? "Object") : "Named";
    default:
      return "Other";
  }
}

/** A field is "inline" when its control fits on one row next to its
 * label (scalars, and unions whose active branch is a scalar) and
 * "block" when it needs a card of its own (objects, dicts, arrays, raw
 * JSON). Depends on the value for unions, so a color entry is a compact
 * row while a derived one is a card. */
export function layoutKind(schema: JSONSchema, defs: Defs, value: unknown): "inline" | "block" {
  const r = resolveRef(schema, defs);
  if (Array.isArray(r.anyOf)) {
    const branches = nonNullBranches(r, defs);
    if (branches.length === 0) return "block";
    if (branches.length === 1) return layoutKind(branches[0], defs, value);
    if (!branchesAreDistinguishable(branches, defs)) return "block";
    return layoutKind(branches[activeBranchIndex(branches, defs, value)], defs, value);
  }
  if (Array.isArray(r.enum)) return "inline";
  switch (r.type) {
    case "string":
    case "number":
    case "integer":
    case "boolean":
      return "inline";
    case undefined:
      // An untyped schema (pydantic's `Any`, e.g. an element's `value`):
      // a string value is edited as text, anything else as raw JSON.
      return typeof value === "string" ? "inline" : "block";
    default:
      return "block";
  }
}

/** True for a schema that constrains nothing (pydantic's `Any`). */
export function isUntyped(schema: JSONSchema): boolean {
  return schema.type === undefined && !schema.$ref && !schema.anyOf && !schema.enum;
}

/** The value a freshly-created entry of this schema starts with. An
 * object gets just its required fields so a new entry is as close to
 * valid as the schema allows. */
export function defaultForSchema(schema: JSONSchema, defs: Defs, depth = 0): unknown {
  const r = resolveRef(schema, defs);
  if (Array.isArray(r.enum) && r.enum.length > 0) return r.enum[0];
  if (Array.isArray(r.anyOf)) {
    const first = nonNullBranches(r, defs)[0];
    return first && depth < 6 ? defaultForSchema(first, defs, depth + 1) : null;
  }
  switch (r.type) {
    case "object": {
      const out: Record<string, unknown> = {};
      const props = (r.properties as Record<string, JSONSchema> | undefined) ?? {};
      for (const key of (r.required as string[] | undefined) ?? []) {
        if (props[key] && depth < 6) out[key] = defaultForSchema(props[key], defs, depth + 1);
      }
      return out;
    }
    case "array":
      return [];
    case "string":
      return "";
    case "number":
    case "integer":
      return 0;
    case "boolean":
      return false;
    default:
      // Untyped (`Any`) values are most often text.
      return isUntyped(r) ? "" : null;
  }
}

/** When switching a union from a string to an object branch, carries the
 * old string into that object's first required string field -- turning a
 * color `"#2457A6"` into `{base: "#2457A6"}` instead of an empty `base`. */
export function seedBranch(branch: JSONSchema, defs: Defs, previous: unknown): unknown {
  const seeded = defaultForSchema(branch, defs);
  if (typeof previous !== "string" || previous === "") return seeded;
  const r = resolveRef(branch, defs);
  if (r.type !== "object" || !seeded || typeof seeded !== "object") return seeded;
  const props = (r.properties as Record<string, JSONSchema> | undefined) ?? {};
  const target = ((r.required as string[] | undefined) ?? []).find(
    (key) => props[key] && jsonTypeOf(props[key], defs) === "string"
  );
  return target ? { ...(seeded as Record<string, unknown>), [target]: previous } : seeded;
}

/** The schema's own default, when it is a scalar worth showing as a
 * placeholder. */
export function placeholderFor(schema: JSONSchema): string | undefined {
  const d = schema.default;
  if (typeof d === "string" && d !== "") return d;
  if (typeof d === "number") return String(d);
  return undefined;
}

// ---- colors ---------------------------------------------------------

export const HEX_COLOR_RE = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

/** `<input type="color">` requires a full 6-digit hex; expands `#abc`
 * to `#aabbcc` purely for that input's own value. */
export function expandHex(hex: string): string {
  if (hex.length !== 4) return hex;
  const [, r, g, b] = hex;
  return `#${r}${r}${g}${g}${b}${b}`;
}

// ---- lengths --------------------------------------------------------

export const LENGTH_UNITS = ["in", "pt", "cm", "mm"] as const;
const LENGTH_RE = /^\s*([+-]?\d*\.?\d+)\s*(in|pt|cm|mm)?\s*$/;

export function parseLength(text: string): { num: string; unit: string } | null {
  const m = LENGTH_RE.exec(text);
  return m ? { num: m[1], unit: m[2] ?? "" } : null;
}

export function composeLength(num: string, unit: string): string {
  return num === "" ? "" : `${num}${unit}`;
}

const UNIT_STEP: Record<string, number> = { in: 0.05, pt: 1, cm: 0.1, mm: 1 };

/** One ArrowUp/ArrowDown step in the unit's natural increment (x10 with
 * Shift), rounded to dodge float noise (`0.1 + 0.2`). */
export function stepLength(num: string, unit: string, direction: 1 | -1, big: boolean): string {
  const base = Number(num);
  const current = Number.isFinite(base) ? base : 0;
  const step = (UNIT_STEP[unit] ?? 1) * (big ? 10 : 1);
  return String(parseFloat((current + direction * step).toFixed(4)));
}
