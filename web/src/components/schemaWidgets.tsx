/**
 * Presentational building blocks for `SchemaForm.tsx`: the small,
 * styled widgets (switch, segmented control, disclosure card, hint,
 * color and length inputs, raw-JSON escape hatch) the recursive
 * renderer assembles. Dependency-free -- plain React and the `sf-*`
 * classes in `App.css`, scoped under `.config-editor`.
 */
import { createContext, useContext, useEffect, useId, useState, type ReactNode } from "react";
import {
  HEX_COLOR_RE,
  LENGTH_UNITS,
  composeLength,
  expandHex,
  parseLength,
  stepLength,
} from "./schemaUtils";

/** Color tokens (`name -> hex`) of the document being edited. A color
 * field shows them as pick-able chips while focused. Empty outside the
 * config editor, so `SchemaForm` stays usable (and testable) alone. */
export const ColorTokensContext = createContext<Record<string, string>>({});

// ---- icons ----------------------------------------------------------

function Chevron() {
  return (
    <svg className="sf-chevron" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M6 3.5 10.5 8 6 12.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

function Cross() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="m4 4 8 8M12 4l-8 8" fill="none" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

// ---- small pieces ---------------------------------------------------

export function Required() {
  return (
    <span className="sf-required" data-required role="img" aria-label="required" title="required">
      <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
        <path
          d="M6 1.2v9.6M1.85 3.6l8.3 4.8M1.85 8.4l8.3-4.8"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          strokeLinecap="round"
        />
      </svg>
    </span>
  );
}

/** One-or-two-line description under a field, expandable when long. */
export function Hint({ text }: { text: unknown }) {
  const [open, setOpen] = useState(false);
  if (typeof text !== "string" || !text.trim()) return null;
  const long = text.length > 110;
  return (
    <div className="sf-hint-wrap">
      <p className={`sf-hint${long && !open ? " sf-hint--clamped" : ""}`}>{text}</p>
      {long && (
        <button
          type="button"
          className="sf-link"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          {open ? "less" : "more"}
        </button>
      )}
    </div>
  );
}

export function Switch({
  checked,
  onChange,
  label,
  id,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  /** Omit when a `<label htmlFor>` already names the switch. */
  label?: string;
  id?: string;
}) {
  return (
    <input
      id={id}
      type="checkbox"
      className="sf-switch"
      aria-label={label}
      checked={checked}
      onChange={(e) => onChange(e.target.checked)}
    />
  );
}

export function Segmented({
  options,
  value,
  onChange,
  label,
  small,
  id,
}: {
  options: { value: string; label: string }[];
  value: string | null;
  onChange: (next: string) => void;
  label: string;
  small?: boolean;
  id?: string;
}) {
  const name = useId();
  return (
    <div
      id={id}
      className={`sf-seg${small ? " sf-seg--small" : ""}`}
      role="radiogroup"
      aria-label={label}
    >
      {options.map((opt) => (
        <label key={opt.value} className="sf-seg__opt">
          <input
            type="radio"
            name={name}
            value={opt.value}
            checked={value === opt.value}
            onChange={() => onChange(opt.value)}
          />
          <span>{opt.label}</span>
        </label>
      ))}
    </div>
  );
}

export function RemoveButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      className="sf-icon-btn sf-icon-btn--danger"
      aria-label={label}
      title={label}
      onClick={onClick}
    >
      <Cross />
    </button>
  );
}

/** A titled card whose body can collapse. `collapsible={false}` keeps
 * the header (and `actions`) but drops the chevron and body -- used for
 * an optional block that is currently unset. */
export function Disclosure({
  label,
  required,
  hint,
  count,
  summary,
  defaultOpen,
  collapsible = true,
  actions,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: unknown;
  count?: number;
  summary?: string;
  defaultOpen: boolean;
  collapsible?: boolean;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();
  const expanded = collapsible && open;
  const title = (
    <>
      {collapsible && <Chevron />}
      <span className="sf-key">{label}</span>
      {required && <Required />}
      {count !== undefined && <span className="sf-count">{count}</span>}
      {summary && <span className="sf-muted">{summary}</span>}
    </>
  );
  return (
    <section className="sf-card" data-open={expanded}>
      <div className="sf-card__head">
        {collapsible ? (
          <button
            type="button"
            className="sf-card__toggle"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={() => setOpen((o) => !o)}
          >
            {title}
          </button>
        ) : (
          <div className="sf-card__toggle sf-card__toggle--static">{title}</div>
        )}
        {actions && <div className="sf-card__actions">{actions}</div>}
      </div>
      {expanded && (
        <div className="sf-card__body" id={bodyId}>
          <Hint text={hint} />
          {children}
        </div>
      )}
    </section>
  );
}

// ---- color ----------------------------------------------------------

/** Swatch (native picker) fused to a text field, plus the document's
 * color tokens as chips while the control has focus. The text field
 * accepts a token name or any literal -- the server validates. */
export function ColorField({
  id,
  value,
  onChange,
  placeholder,
}: {
  id?: string;
  value: unknown;
  onChange: (next: string) => void;
  placeholder?: string;
}) {
  const tokens = useContext(ColorTokensContext);
  const text = typeof value === "string" ? value : "";
  const resolved = HEX_COLOR_RE.test(text) ? text : (tokens[text] ?? "");
  const swatch = HEX_COLOR_RE.test(resolved) ? expandHex(resolved) : "#ffffff";
  const names = Object.keys(tokens);
  return (
    <div className="sf-color">
      <div className="sf-color__field">
        <input
          type="color"
          className="sf-color__swatch"
          aria-label="color picker"
          data-empty={!HEX_COLOR_RE.test(resolved)}
          value={swatch}
          onChange={(e) => onChange(e.target.value)}
        />
        <input
          id={id}
          type="text"
          className="sf-control sf-control--mono sf-color__text"
          value={text}
          placeholder={placeholder}
          spellCheck={false}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
      {names.length > 0 && (
        // Keep focus on the field while a chip is pressed (Safari does
        // not focus buttons on click), so the popover stays open.
        <div className="sf-chips" role="group" aria-label="Color tokens" onMouseDown={(e) => e.preventDefault()}>
          {names.map((name) => (
            <button
              key={name}
              type="button"
              className="sf-chip"
              data-active={name === text}
              title={tokens[name]}
              onClick={() => onChange(name)}
            >
              <span className="sf-chip__dot" style={{ background: tokens[name] }} />
              {name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---- length ---------------------------------------------------------

/** Number + unit select for a `0.75in`-style string, with ArrowUp/Down
 * stepping in the unit's natural increment (Shift = x10). A value that
 * does not match the grammar (hand-typed, or from an older file) falls
 * back to one plain text input, flagged invalid but still editable --
 * the server stays the authoritative validator. */
export function LengthField({
  id,
  value,
  onChange,
  placeholder,
}: {
  id?: string;
  value: unknown;
  onChange: (next: string) => void;
  placeholder?: string;
}) {
  const text = typeof value === "string" ? value : "";
  const initial = parseLength(text);
  const [plain, setPlain] = useState(text !== "" && !initial);
  const [num, setNum] = useState(initial?.num ?? "");
  const [unit, setUnit] = useState(initial?.unit ?? "in");

  // Re-sync when the value changed from outside (Revert, Raw view, a
  // sibling field) rather than from this widget's own edits.
  useEffect(() => {
    if (text === composeLength(num, unit)) return;
    const parsed = parseLength(text);
    if (parsed) {
      setNum(parsed.num);
      setUnit(parsed.unit);
      setPlain(false);
    } else {
      setNum("");
      setPlain(text !== "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  if (plain) {
    return (
      <input
        id={id}
        type="text"
        className="sf-control sf-control--mono"
        aria-invalid="true"
        title="Expected a number with a unit: in, pt, cm or mm"
        value={text}
        placeholder={placeholder}
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  return (
    <div className="sf-length">
      <input
        id={id}
        type="text"
        inputMode="decimal"
        className="sf-control sf-control--mono sf-length__num"
        value={num}
        placeholder={parseLength(placeholder ?? "")?.num}
        spellCheck={false}
        onChange={(e) => {
          setNum(e.target.value);
          onChange(composeLength(e.target.value, unit));
        }}
        onKeyDown={(e) => {
          if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
          e.preventDefault();
          const next = stepLength(num, unit, e.key === "ArrowUp" ? 1 : -1, e.shiftKey);
          setNum(next);
          onChange(composeLength(next, unit));
        }}
      />
      <select
        className="sf-control sf-select sf-length__unit"
        aria-label="unit"
        value={unit}
        onChange={(e) => {
          setUnit(e.target.value);
          onChange(composeLength(num, e.target.value));
        }}
      >
        {unit === "" && <option value="">—</option>}
        {LENGTH_UNITS.map((u) => (
          <option key={u} value={u}>
            {u}
          </option>
        ))}
      </select>
    </div>
  );
}

// ---- raw JSON escape hatch -----------------------------------------

/** A plain JSON textarea for one value the form cannot model (a union
 * whose branches share a JSON type, or an unrecognised shape). Keeps its
 * own text so an in-progress, momentarily invalid edit is never
 * clobbered; re-syncs when `value` changes from outside. */
export function RawJsonField({
  value,
  onChange,
}: {
  value: unknown;
  onChange: (next: unknown) => void;
}) {
  const [text, setText] = useState(() => JSON.stringify(value ?? null, null, 2));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setText(JSON.stringify(value ?? null, null, 2));
    setError(null);
  }, [value]);

  function handleChange(next: string) {
    setText(next);
    try {
      onChange(JSON.parse(next));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="sf-raw">
      <textarea
        className="sf-control sf-control--mono sf-raw__textarea"
        aria-invalid={error ? "true" : undefined}
        value={text}
        spellCheck={false}
        rows={Math.min(8, Math.max(2, text.split("\n").length))}
        onChange={(e) => handleChange(e.target.value)}
      />
      {error && <span className="sf-raw__error">{error}</span>}
    </div>
  );
}
