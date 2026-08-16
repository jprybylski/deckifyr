/**
 * A recursive form renderer driven by `GET /api/schemas/{doc}`'s JSON
 * Schema output (issue #22's "form-based editor... similar to what is
 * achieved in the slide editor") -- `ConfigEditor.tsx`'s own module
 * docstring previously flagged this as explicit future scope; this is
 * that scope, now built. Confirmed the schema shape against a real
 * `uv run deckifyr schema design` dump before writing this (standard
 * pydantic output: a top-level `$defs` map, `$ref`s pointing into it,
 * and `X | None` fields as `anyOf: [{...}, {"type": "null"}]`).
 *
 * Deliberately not a full JSON-Schema-draft implementation. It handles
 * the shapes this repo's own schemas actually use: `$ref`/`$defs`,
 * `type: "object"` with fixed `properties` (a labeled field per
 * property, `anyOf`-with-null unwrapped into a set/unset checkbox),
 * `type: "object"` with `additionalProperties` and no fixed properties
 * (open dicts like `colors`/`text_styles`/`shape_styles`/`table_styles`
 * -- an add/remove named-entry list), `enum` (`<select>`), plain
 * `string`/`number`/`integer`/`boolean`, and `type: "array"` (repeatable
 * `items`-schema rows, add/remove only, no reordering). An `anyOf`/
 * `oneOf` with more than one *non-null* branch (e.g. `colors`' own
 * `str | ColorDerivation` entry values) can't be disambiguated
 * generically, so it -- and anything else this renderer doesn't
 * recognize -- falls back to a small inline raw-JSON field for just
 * that one leaf value, rather than guessing wrong. This is the same
 * kind of honest, narrow scope boundary this repo already keeps
 * elsewhere (CLAUDE.md: `render_mode: svg`, unset `table_style`).
 *
 * Server-side `model_validate` (already wired in `deckifyr.web.app`'s
 * `put_config`) remains the authoritative validator -- this renderer
 * only tracks types/shape, not cross-field business rules (e.g.
 * `PresentationDocument`'s `status_indicator`/`watermark` interaction),
 * the same division of responsibility `ConfigEditor.tsx`'s Raw view has
 * with the server today.
 */
import { useEffect, useState } from "react";

export type JSONSchema = Record<string, unknown>;

interface Props {
  schema: JSONSchema;
  defs: Record<string, JSONSchema>;
  value: unknown;
  onChange: (value: unknown) => void;
}

function resolveRef(schema: JSONSchema, defs: Record<string, JSONSchema>): JSONSchema {
  let current = schema;
  for (let guard = 0; guard < 10 && typeof current.$ref === "string"; guard += 1) {
    const name = (current.$ref as string).replace(/^#\/\$defs\//, "");
    const next = defs[name];
    if (!next) break;
    current = next;
  }
  return current;
}

function isNullSchema(schema: JSONSchema): boolean {
  return schema.type === "null";
}

/** Unwraps an `anyOf` with exactly one non-null branch (pydantic's
 * `X | None` shape) into that branch plus a `nullable` flag. Returns
 * `inner: null` when there isn't exactly one non-null branch (0, or 2+
 * -- a real union this renderer can't disambiguate), signaling the
 * caller to fall back to a raw-JSON field.
 */
function unwrapNullable(
  schema: JSONSchema,
  defs: Record<string, JSONSchema>
): { inner: JSONSchema | null; nullable: boolean } {
  const anyOf = schema.anyOf;
  if (!Array.isArray(anyOf)) return { inner: schema, nullable: false };
  const branches = anyOf as JSONSchema[];
  const nullable = branches.some((branch) => isNullSchema(resolveRef(branch, defs)));
  const nonNull = branches.filter((branch) => !isNullSchema(resolveRef(branch, defs)));
  if (nonNull.length === 1) {
    return { inner: nonNull[0], nullable };
  }
  return { inner: null, nullable };
}

const HEX_COLOR_RE = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

/** `<input type="color">` requires a full 6-digit hex -- expands a
 * 3-digit shorthand (`#abc` -> `#aabbcc`) purely for that input's own
 * `value`; the paired text field always keeps whatever the document
 * actually holds, shorthand or not. */
function _expandHexShorthand(hex: string): string {
  const [, r, g, b] = hex;
  return `#${r}${r}${g}${g}${b}${b}`;
}

function defaultForSchema(schema: JSONSchema): unknown {
  if (Array.isArray(schema.enum) && schema.enum.length > 0) {
    return (schema.enum as unknown[])[0];
  }
  switch (schema.type) {
    case "object":
      return {};
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
      return null;
  }
}

/** The documented escape hatch: a plain JSON textarea for one leaf
 * value, used whenever this renderer can't confidently model a
 * schema shape. Re-syncs its local text from `value` whenever `value`
 * changes from outside (including its own successful `onChange` calls,
 * which is harmless -- it just re-serializes to the same content).
 *
 * Also gets its own color swatch (issue #23) whenever the *current
 * value* is a literal hex string, independent of the schema-shape
 * fallback that put it here in the first place -- `colors:`'s own entry
 * schema is exactly this ambiguous-anyOf case (`str | ColorDerivation`)
 * for every project, including one that only ever uses plain hex
 * literals, so without this the swatch from the plain-`string`-schema
 * branch below would never actually reach the one field (`colors:`)
 * issue #23's own "a little box showing the color" ask was most likely
 * about. Confirmed against a real `deckifyr serve` session, not assumed
 * from the schema alone -- `examples/demo-deck/design.yaml`'s `colors:`
 * block renders through this exact fallback. */
function RawJsonField({ value, onChange }: { value: unknown; onChange: (next: unknown) => void }) {
  const [text, setText] = useState(() => JSON.stringify(value ?? null, null, 2));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setText(JSON.stringify(value ?? null, null, 2));
    setError(null);
  }, [value]);

  function handleChange(next: string) {
    setText(next);
    try {
      const parsed = JSON.parse(next);
      setError(null);
      onChange(parsed);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const isHexColor = typeof value === "string" && HEX_COLOR_RE.test(value);

  return (
    <div className="schema-form__raw">
      {isHexColor && (
        <input
          type="color"
          className="schema-form__color-swatch"
          aria-label="color picker"
          value={(value as string).length === 4 ? _expandHexShorthand(value as string) : value}
          onChange={(e) => handleChange(JSON.stringify(e.target.value))}
        />
      )}
      <textarea
        className="schema-form__raw-textarea"
        value={text}
        spellCheck={false}
        rows={Math.min(6, Math.max(2, text.split("\n").length))}
        onChange={(e) => handleChange(e.target.value)}
      />
      {error && <span className="schema-form__raw-error">{error}</span>}
    </div>
  );
}

function NullableField({
  inner,
  defs,
  value,
  onChange,
}: {
  inner: JSONSchema;
  defs: Record<string, JSONSchema>;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const isSet = value !== null && value !== undefined;
  return (
    <div className="schema-form__nullable">
      <label className="schema-form__nullable-toggle">
        <input
          type="checkbox"
          checked={isSet}
          onChange={(e) => {
            if (e.target.checked) {
              onChange(defaultForSchema(resolveRef(inner, defs)));
            } else {
              onChange(null);
            }
          }}
        />
        set
      </label>
      {isSet && <SchemaForm schema={inner} defs={defs} value={value} onChange={onChange} />}
    </div>
  );
}

function ObjectFields({
  schema,
  defs,
  value,
  onChange,
}: {
  schema: JSONSchema;
  defs: Record<string, JSONSchema>;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
}) {
  const properties = (schema.properties as Record<string, JSONSchema> | undefined) ?? {};
  const required = new Set((schema.required as string[] | undefined) ?? []);
  return (
    <div className="schema-form__object">
      {Object.entries(properties).map(([key, propSchema]) => (
        <div className="schema-form__field" key={key}>
          <label className="schema-form__field-label">
            {key}
            {required.has(key) && <span className="schema-form__required"> *</span>}
          </label>
          <SchemaForm
            schema={propSchema}
            defs={defs}
            value={value[key]}
            onChange={(next) => onChange({ ...value, [key]: next })}
          />
        </div>
      ))}
    </div>
  );
}

function OpenDictFields({
  itemSchema,
  defs,
  value,
  onChange,
}: {
  itemSchema: JSONSchema;
  defs: Record<string, JSONSchema>;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
}) {
  const [newKey, setNewKey] = useState("");
  const entries = Object.entries(value);

  return (
    <div className="schema-form__dict">
      {entries.map(([key, entryValue]) => (
        <div className="schema-form__dict-entry" key={key}>
          <div className="schema-form__dict-entry-header">
            <strong>{key}</strong>
            <button
              type="button"
              onClick={() => {
                const next = { ...value };
                delete next[key];
                onChange(next);
              }}
            >
              Remove
            </button>
          </div>
          <SchemaForm
            schema={itemSchema}
            defs={defs}
            value={entryValue}
            onChange={(next) => onChange({ ...value, [key]: next })}
          />
        </div>
      ))}
      <div className="schema-form__dict-add">
        <input
          placeholder="new key"
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
        />
        <button
          type="button"
          disabled={!newKey || newKey in value}
          onClick={() => {
            onChange({ ...value, [newKey]: defaultForSchema(resolveRef(itemSchema, defs)) });
            setNewKey("");
          }}
        >
          Add
        </button>
      </div>
    </div>
  );
}

function ArrayFields({
  itemSchema,
  defs,
  value,
  onChange,
}: {
  itemSchema: JSONSchema;
  defs: Record<string, JSONSchema>;
  value: unknown[];
  onChange: (value: unknown[]) => void;
}) {
  return (
    <div className="schema-form__array">
      {value.map((item, index) => (
        // No stable id for a plain array item -- add/remove-only (no
        // reorder) makes index-as-key safe here.
        <div className="schema-form__array-item" key={index}>
          <SchemaForm
            schema={itemSchema}
            defs={defs}
            value={item}
            onChange={(next) => {
              const copy = [...value];
              copy[index] = next;
              onChange(copy);
            }}
          />
          <button type="button" onClick={() => onChange(value.filter((_, i) => i !== index))}>
            Remove
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={() => onChange([...value, defaultForSchema(resolveRef(itemSchema, defs))])}
      >
        Add item
      </button>
    </div>
  );
}

function EnumField({
  options,
  value,
  onChange,
}: {
  options: unknown[];
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  return (
    <select value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
      {options.map((opt) => (
        <option key={String(opt)} value={String(opt)}>
          {String(opt)}
        </option>
      ))}
    </select>
  );
}

export default function SchemaForm({ schema, defs, value, onChange }: Props) {
  const resolved = resolveRef(schema, defs);

  if (Array.isArray(resolved.anyOf)) {
    const { inner, nullable } = unwrapNullable(resolved, defs);
    if (inner && nullable) {
      return <NullableField inner={inner} defs={defs} value={value} onChange={onChange} />;
    }
    if (inner) {
      // A non-nullable anyOf with exactly one real branch (unusual, but
      // handled the same as if it were the branch itself).
      return <SchemaForm schema={inner} defs={defs} value={value} onChange={onChange} />;
    }
    return <RawJsonField value={value} onChange={onChange} />;
  }

  if (Array.isArray(resolved.enum)) {
    return <EnumField options={resolved.enum as unknown[]} value={value} onChange={onChange} />;
  }

  if (resolved.type === "object") {
    if (resolved.properties) {
      return (
        <ObjectFields
          schema={resolved}
          defs={defs}
          value={(value as Record<string, unknown>) ?? {}}
          onChange={onChange as (value: Record<string, unknown>) => void}
        />
      );
    }
    if (resolved.additionalProperties && typeof resolved.additionalProperties === "object") {
      return (
        <OpenDictFields
          itemSchema={resolved.additionalProperties as JSONSchema}
          defs={defs}
          value={(value as Record<string, unknown>) ?? {}}
          onChange={onChange as (value: Record<string, unknown>) => void}
        />
      );
    }
    return <RawJsonField value={value} onChange={onChange} />;
  }

  if (resolved.type === "array") {
    return (
      <ArrayFields
        itemSchema={(resolved.items as JSONSchema) ?? {}}
        defs={defs}
        value={(value as unknown[]) ?? []}
        onChange={onChange as (value: unknown[]) => void}
      />
    );
  }

  if (resolved.type === "string") {
    const text = typeof value === "string" ? value : "";
    // A small swatch + native color picker (issue #23) whenever the
    // field's *current value* is already a literal hex color -- no
    // field-name heuristic (a `colors:` entry's key is an arbitrary
    // token name, not necessarily containing "color"), so this works
    // generically for `colors:` entries, gradient stops, table-style
    // colors, anywhere a literal hex is already stored. A token string
    // (e.g. "primary", used elsewhere via `design.colors.get(token,
    // token)`'s own "token or bare literal" fallback) just shows the
    // plain text input, same as before this existed, until it holds a
    // real hex value.
    const isHexColor = HEX_COLOR_RE.test(text);
    return (
      <span className="schema-form__string">
        <input type="text" value={text} onChange={(e) => onChange(e.target.value)} />
        {isHexColor && (
          <input
            type="color"
            className="schema-form__color-swatch"
            aria-label="color picker"
            value={text.length === 4 ? _expandHexShorthand(text) : text}
            onChange={(e) => onChange(e.target.value)}
          />
        )}
      </span>
    );
  }

  if (resolved.type === "number" || resolved.type === "integer") {
    return (
      <input
        type="number"
        value={typeof value === "number" ? value : ""}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
      />
    );
  }

  if (resolved.type === "boolean") {
    return (
      <input
        type="checkbox"
        checked={Boolean(value)}
        onChange={(e) => onChange(e.target.checked)}
      />
    );
  }

  return <RawJsonField value={value} onChange={onChange} />;
}
