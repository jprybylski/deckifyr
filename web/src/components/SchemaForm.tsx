/**
 * Schema-driven form for `design.yaml`/`layouts.yaml`/`presentation.yaml`
 * (issue #22, restyled and extended in the config-form redesign).
 * Renders a JSON Schema as typed, labelled fields, so `ConfigEditor.tsx`
 * can offer something friendlier than a JSON textarea while the
 * server's own schema (`GET /api/schemas/{doc}`) stays the single source
 * of truth for what exists.
 *
 * Deliberately not a full JSON-Schema-draft implementation -- it handles
 * the shapes pydantic emits for these three models:
 *
 * - `$ref`/`$defs`.
 * - Objects with fixed `properties`: one row per property -- the raw key
 *   as a monospace tag (the same spelling the YAML uses), the schema's
 *   own `description` as a hint, its `default` as a placeholder. A
 *   scalar sits inline; an object/dict/array becomes a collapsible card.
 * - `X | None` (`anyOf` with a null branch): an on/off switch in the
 *   field's own row, revealing the field when set.
 * - Unions of differently-typed branches (`str | ColorDerivation`,
 *   `str | Gradient`, `dict | list`): a segmented switch between the
 *   branches, the active one inferred from the value. Branches sharing a
 *   JSON type cannot be told apart generically and fall back to raw JSON.
 * - Open dicts (`additionalProperties`, no `properties`): named entries
 *   with add/remove. Arrays: add/remove, no reordering.
 * - Enums: a segmented control when short (<= 4 short options), else a
 *   select. Strings annotated `x-deckifyr-widget: color|length` (see
 *   `schema/fields.py`) get a color picker with token chips or a
 *   unit-aware number input; any string already holding a hex color
 *   also gets a swatch.
 * - Anything unrecognised: the raw-JSON field, as the escape hatch.
 *
 * The server's `model_validate` stays authoritative: the form tracks
 * types and shape, not cross-field rules (e.g. "exactly one of
 * lighten/darken/..." on a color derivation).
 */
import { useId, useRef, useState } from "react";
import {
  Disclosure,
  Hint,
  RawJsonField,
  RemoveButton,
  Required,
  ColorField,
  LengthField,
  Segmented,
  Switch,
} from "./schemaWidgets";
import {
  HEX_COLOR_RE,
  WIDGET_KEY,
  activeBranchIndex,
  branchLabel,
  branchesAreDistinguishable,
  defaultForSchema,
  expandHex,
  hasNullBranch,
  isUntyped,
  layoutKind,
  nonNullBranches,
  placeholderFor,
  resolveRef,
  seedBranch,
  unwrapNullable,
  type Defs,
  type JSONSchema,
} from "./schemaUtils";

export type { JSONSchema } from "./schemaUtils";

interface Props {
  schema: JSONSchema;
  defs: Defs;
  value: unknown;
  onChange: (value: unknown) => void;
  /** Id for the primary control, so a field's `<label htmlFor>` works. */
  id?: string;
  /** Nesting depth; deeper cards start collapsed. */
  depth?: number;
  placeholder?: string;
}

const MaybeMuted = ({ children }: { children: string }) => <span className="sf-muted">{children}</span>;

// ---- containers -----------------------------------------------------

function FieldRow({
  name,
  propSchema,
  required,
  defs,
  value,
  onChange,
  depth,
}: {
  name: string;
  propSchema: JSONSchema;
  required: boolean;
  defs: Defs;
  value: unknown;
  onChange: (next: unknown) => void;
  depth: number;
}) {
  const id = useId();
  const resolved = resolveRef(propSchema, defs);
  const { inner, nullable } = unwrapNullable(resolved, defs);
  const target = inner ?? resolved;
  const isSet = !nullable || (value !== null && value !== undefined);
  // Only a property's *own* description is a hint -- a `$defs` entry's
  // description is its class docstring, written for developers.
  const hint = propSchema.description;
  const toggle = (on: boolean) => onChange(on ? defaultForSchema(target, defs) : null);
  const kind = layoutKind(target, defs, value);
  // A union keeps one wrapper whichever branch is active: switching to a
  // card-shaped branch must not remount the field (it would drop the
  // branch memory and collapse state), so only non-unions become cards.
  const isUnion = Array.isArray(target.anyOf);

  if (kind === "block" && !isUnion) {
    const collection =
      isSet && target.type === "object" && !target.properties
        ? Object.keys((value as Record<string, unknown>) ?? {}).length
        : isSet && Array.isArray(value)
          ? value.length
          : undefined;
    return (
      <Disclosure
        label={name}
        required={required}
        hint={hint}
        count={collection}
        summary={isSet ? undefined : "Not set"}
        collapsible={isSet}
        defaultOpen={depth < 2}
        actions={nullable && <Switch checked={isSet} onChange={toggle} label={`Set ${name}`} />}
      >
        <SchemaForm schema={target} defs={defs} value={value} onChange={onChange} depth={depth + 1} />
      </Disclosure>
    );
  }

  return (
    <div className="sf-row" data-set={isSet} data-kind={kind}>
      <div className="sf-row__label">
        <label htmlFor={id}>
          <span className="sf-key">{name}</span>
        </label>
        {required && <Required />}
      </div>
      <div className="sf-row__main">
        <div className="sf-row__control">
          {nullable && <Switch checked={isSet} onChange={toggle} label={`Set ${name}`} />}
          {isSet ? (
            <SchemaForm
              id={id}
              schema={target}
              defs={defs}
              value={value}
              onChange={onChange}
              depth={depth + 1}
              placeholder={placeholderFor(propSchema)}
            />
          ) : (
            <MaybeMuted>Not set</MaybeMuted>
          )}
        </div>
        <Hint text={hint} />
      </div>
    </div>
  );
}

function ObjectFields({
  schema,
  defs,
  value,
  onChange,
  depth,
}: {
  schema: JSONSchema;
  defs: Defs;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  depth: number;
}) {
  const properties = (schema.properties as Record<string, JSONSchema> | undefined) ?? {};
  const required = new Set((schema.required as string[] | undefined) ?? []);
  return (
    <div className="sf-object">
      {Object.entries(properties).map(([key, propSchema]) => (
        <FieldRow
          key={key}
          name={key}
          propSchema={propSchema}
          required={required.has(key)}
          defs={defs}
          value={value[key]}
          depth={depth}
          onChange={(next) => onChange({ ...value, [key]: next })}
        />
      ))}
    </div>
  );
}

function OpenDictFields({
  itemSchema,
  defs,
  value,
  onChange,
  depth,
}: {
  itemSchema: JSONSchema;
  defs: Defs;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  depth: number;
}) {
  const [newKey, setNewKey] = useState("");
  const entries = Object.entries(value);
  const canAdd = newKey !== "" && !(newKey in value);

  function add() {
    if (!canAdd) return;
    onChange({ ...value, [newKey]: defaultForSchema(itemSchema, defs) });
    setNewKey("");
  }

  return (
    <div className="sf-dict">
      {entries.length === 0 && <p className="sf-empty">No entries yet.</p>}
      {entries.map(([key, entryValue]) => {
        const remove = () => {
          const next = { ...value };
          delete next[key];
          onChange(next);
        };
        const setEntry = (next: unknown) => onChange({ ...value, [key]: next });
        const kind = layoutKind(itemSchema, defs, entryValue);
        if (kind === "inline" || Array.isArray(resolveRef(itemSchema, defs).anyOf)) {
          return (
            <div className="sf-entry" key={key} data-kind={kind}>
              <span className="sf-key sf-entry__key">{key}</span>
              <div className="sf-entry__control">
                <SchemaForm
                  schema={itemSchema}
                  defs={defs}
                  value={entryValue}
                  onChange={setEntry}
                  depth={depth + 1}
                />
              </div>
              <RemoveButton label={`Remove ${key}`} onClick={remove} />
            </div>
          );
        }
        return (
          <Disclosure
            key={key}
            label={key}
            defaultOpen={entries.length <= 3}
            actions={<RemoveButton label={`Remove ${key}`} onClick={remove} />}
          >
            <SchemaForm
              schema={itemSchema}
              defs={defs}
              value={entryValue}
              onChange={setEntry}
              depth={depth + 1}
            />
          </Disclosure>
        );
      })}
      <div className="sf-add">
        <input
          className="sf-control"
          placeholder="new key"
          aria-label="new key"
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <button type="button" className="sf-btn sf-btn--soft sf-btn--add" disabled={!canAdd} onClick={add}>
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
  depth,
}: {
  itemSchema: JSONSchema;
  defs: Defs;
  value: unknown[];
  onChange: (value: unknown[]) => void;
  depth: number;
}) {
  return (
    <div className="sf-array">
      {value.length === 0 && <p className="sf-empty">No items yet.</p>}
      {value.map((item, index) => {
        const remove = () => onChange(value.filter((_, i) => i !== index));
        const setItem = (next: unknown) => {
          const copy = [...value];
          copy[index] = next;
          onChange(copy);
        };
        // No stable id for a plain array item -- add/remove-only (no
        // reorder) makes index-as-key safe here.
        const kind = layoutKind(itemSchema, defs, item);
        if (kind === "inline" || Array.isArray(resolveRef(itemSchema, defs).anyOf)) {
          return (
            <div className="sf-entry" key={index} data-kind={kind}>
              <span className="sf-key sf-entry__key">#{index + 1}</span>
              <div className="sf-entry__control">
                <SchemaForm schema={itemSchema} defs={defs} value={item} onChange={setItem} depth={depth + 1} />
              </div>
              <RemoveButton label={`Remove item ${index + 1}`} onClick={remove} />
            </div>
          );
        }
        return (
          <Disclosure
            key={index}
            label={`#${index + 1}`}
            defaultOpen={value.length <= 3}
            actions={<RemoveButton label={`Remove item ${index + 1}`} onClick={remove} />}
          >
            <SchemaForm schema={itemSchema} defs={defs} value={item} onChange={setItem} depth={depth + 1} />
          </Disclosure>
        );
      })}
      <button
        type="button"
        className="sf-btn sf-btn--dashed sf-btn--add"
        onClick={() => onChange([...value, defaultForSchema(itemSchema, defs)])}
      >
        Add item
      </button>
    </div>
  );
}

// ---- optional and union values --------------------------------------

/** Toggle + inner form, for an optional value outside an object row
 * (array items, dict entries, the root). Object properties handle their
 * own optionality in `FieldRow`, in the field's own row. */
function NullableField({
  inner,
  defs,
  value,
  onChange,
  depth,
}: {
  inner: JSONSchema;
  defs: Defs;
  value: unknown;
  onChange: (value: unknown) => void;
  depth: number;
}) {
  const isSet = value !== null && value !== undefined;
  return (
    <div className="sf-nullable">
      <div className="sf-nullable__bar">
        <Switch
          checked={isSet}
          label="set"
          onChange={(on) => onChange(on ? defaultForSchema(inner, defs) : null)}
        />
        {!isSet && <MaybeMuted>Not set</MaybeMuted>}
      </div>
      {isSet && <SchemaForm schema={inner} defs={defs} value={value} onChange={onChange} depth={depth} />}
    </div>
  );
}

function UnionField({
  branches,
  defs,
  value,
  onChange,
  depth,
  id,
}: {
  branches: JSONSchema[];
  defs: Defs;
  value: unknown;
  onChange: (value: unknown) => void;
  depth: number;
  id?: string;
}) {
  // Each branch's last value, so an accidental switch is undoable.
  const remembered = useRef<Record<number, unknown>>({});
  if (!branchesAreDistinguishable(branches, defs)) {
    return <RawJsonField value={value} onChange={onChange} />;
  }
  const active = activeBranchIndex(branches, defs, value);
  const options = branches.map((branch, i) => ({ value: String(i), label: branchLabel(branch, defs) }));

  function switchTo(next: number) {
    remembered.current[active] = value;
    onChange(next in remembered.current ? remembered.current[next] : seedBranch(branches[next], defs, value));
  }

  const kind = layoutKind(branches[active], defs, value);
  return (
    <div className={`sf-union sf-union--${kind}`}>
      <Segmented
        small
        label="Value type"
        options={options}
        value={String(active)}
        onChange={(v) => switchTo(Number(v))}
      />
      <div className="sf-union__body">
        <SchemaForm id={id} schema={branches[active]} defs={defs} value={value} onChange={onChange} depth={depth} />
      </div>
    </div>
  );
}

function EnumField({
  id,
  options,
  value,
  onChange,
}: {
  id?: string;
  options: unknown[];
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const labels = options.map(String);
  const current = value === null || value === undefined ? "" : String(value);
  if (labels.length <= 4 && labels.join("").length <= 40) {
    return (
      <Segmented
        id={id}
        label="Options"
        options={labels.map((l) => ({ value: l, label: l }))}
        value={current}
        onChange={onChange}
      />
    );
  }
  return (
    <select id={id} className="sf-control sf-select" value={current} onChange={(e) => onChange(e.target.value)}>
      {!labels.includes(current) && <option value="">—</option>}
      {labels.map((opt) => (
        <option key={opt} value={opt}>
          {opt}
        </option>
      ))}
    </select>
  );
}

// ---- entry point ----------------------------------------------------

export default function SchemaForm({ schema, defs, value, onChange, id, depth = 0, placeholder }: Props) {
  const resolved = resolveRef(schema, defs);

  if (Array.isArray(resolved.anyOf)) {
    const branches = nonNullBranches(resolved, defs);
    if (branches.length === 0) return <RawJsonField value={value} onChange={onChange} />;
    if (hasNullBranch(resolved, defs)) {
      const inner = branches.length === 1 ? branches[0] : { anyOf: branches };
      return <NullableField inner={inner} defs={defs} value={value} onChange={onChange} depth={depth} />;
    }
    if (branches.length === 1) {
      return <SchemaForm id={id} schema={branches[0]} defs={defs} value={value} onChange={onChange} depth={depth} />;
    }
    return <UnionField id={id} branches={branches} defs={defs} value={value} onChange={onChange} depth={depth} />;
  }

  if (Array.isArray(resolved.enum)) {
    return <EnumField id={id} options={resolved.enum as unknown[]} value={value} onChange={onChange} />;
  }

  if (resolved.type === "object") {
    if (resolved.properties) {
      return (
        <ObjectFields
          schema={resolved}
          defs={defs}
          value={(value as Record<string, unknown>) ?? {}}
          onChange={onChange as (value: Record<string, unknown>) => void}
          depth={depth}
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
          depth={depth}
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
        depth={depth}
      />
    );
  }

  if (resolved.type === "string") {
    const text = typeof value === "string" ? value : "";
    const widget = resolved[WIDGET_KEY];
    if (widget === "color") {
      return <ColorField id={id} value={text} onChange={onChange} placeholder={placeholder} />;
    }
    if (widget === "length") {
      return <LengthField id={id} value={text} onChange={onChange} placeholder={placeholder} />;
    }
    // A plain string already holding a literal hex color still gets a
    // swatch (no field-name heuristic -- `colors:` entries, gradient
    // stops, anywhere a hex is stored). The swatch is a conditional
    // *sibling before* the input, so the input keeps its place in the
    // tree (and its focus) the moment typing turns the text into a hex.
    const isHex = HEX_COLOR_RE.test(text);
    return (
      <span className="sf-string">
        {isHex && (
          <input
            type="color"
            className="sf-color__swatch"
            aria-label="color picker"
            value={expandHex(text)}
            onChange={(e) => onChange(e.target.value)}
          />
        )}
        <input
          id={id}
          type="text"
          className="sf-control"
          value={text}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      </span>
    );
  }

  if (resolved.type === "number" || resolved.type === "integer") {
    return (
      <input
        id={id}
        type="number"
        className="sf-control sf-control--number"
        step={resolved.type === "integer" ? 1 : "any"}
        value={typeof value === "number" ? value : ""}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
      />
    );
  }

  if (resolved.type === "boolean") {
    return <Switch id={id} checked={Boolean(value)} onChange={onChange} />;
  }

  if (isUntyped(resolved) && typeof value === "string") {
    // Always a textarea (never swapping input kinds on a keystroke), so
    // multi-line Markdown stays editable without losing focus.
    return (
      <textarea
        id={id}
        className="sf-control sf-control--text"
        rows={Math.min(8, Math.max(2, value.split("\n").length))}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  return <RawJsonField value={value} onChange={onChange} />;
}
