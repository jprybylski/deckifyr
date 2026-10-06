/**
 * Splits a config document's schema into the sections `ConfigEditor`'s
 * left rail lists: every top-level scalar property is grouped into one
 * "General" section, and each top-level object/dict/array gets a section
 * of its own, so a long document shows one focused pane at a time rather
 * than one endless scroll. Pure functions over plain schema/value data.
 */
import { layoutKind, resolveRef, type Defs, type JSONSchema } from "./components/schemaUtils";

export const GENERAL_ID = "__general__";

export interface Section {
  id: string;
  label: string;
  /** Top-level property names this section edits. */
  keys: string[];
  /** Entry count for a dict/array section, shown as a badge. */
  count?: number;
}

export function buildSections(schema: JSONSchema, defs: Defs, value: Record<string, unknown>): Section[] {
  const properties = (schema.properties as Record<string, JSONSchema> | undefined) ?? {};
  const general: string[] = [];
  const blocks: Section[] = [];
  for (const [key, prop] of Object.entries(properties)) {
    if (layoutKind(prop, defs, value[key]) === "inline") {
      general.push(key);
      continue;
    }
    const resolved = resolveRef(prop, defs);
    const entry = value[key];
    const count = Array.isArray(entry)
      ? entry.length
      : resolved.type === "object" && !resolved.properties && entry && typeof entry === "object"
        ? Object.keys(entry).length
        : undefined;
    blocks.push({ id: key, label: key, keys: [key], count });
  }
  return general.length ? [{ id: GENERAL_ID, label: "General", keys: general }, ...blocks] : blocks;
}

/** The schema a section's form renders: the property itself for a
 * single-property section, or the document schema narrowed to the
 * section's own keys for "General". */
export function sectionSchema(schema: JSONSchema, section: Section): JSONSchema {
  const properties = (schema.properties as Record<string, JSONSchema> | undefined) ?? {};
  if (section.id !== GENERAL_ID) return properties[section.keys[0]] ?? {};
  const required = ((schema.required as string[] | undefined) ?? []).filter((k) => section.keys.includes(k));
  return {
    type: "object",
    properties: Object.fromEntries(section.keys.map((k) => [k, properties[k]])),
    required,
  };
}

export function sectionValue(value: Record<string, unknown>, section: Section): unknown {
  if (section.id !== GENERAL_ID) return value[section.keys[0]];
  return Object.fromEntries(section.keys.map((k) => [k, value[k]]));
}

/** Writes one section's edited value back into the whole document. */
export function applySection(
  value: Record<string, unknown>,
  section: Section,
  next: unknown
): Record<string, unknown> {
  if (section.id !== GENERAL_ID) return { ...value, [section.keys[0]]: next };
  return { ...value, ...(next as Record<string, unknown>) };
}
