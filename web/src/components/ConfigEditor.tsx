/**
 * Editor for `design.yaml`/`layouts.yaml`/`presentation.yaml`, with two
 * views a user can switch between (issue #22):
 *
 * - **Form** (default): `SchemaForm.tsx`, driven by `GET /api/schemas/
 *   {doc}` -- typed fields instead of raw text. Previously-documented
 *   future scope, now built; see that module's own docstring for what
 *   it does and doesn't model.
 * - **Raw**: pretty-printed **JSON, not YAML** -- still a deliberate
 *   simplification, not an oversight (see the reasoning this module
 *   docstring used to carry: `GET`/`PUT /api/config/{doc}` are already
 *   JSON-native end to end, and a real YAML round trip needs comments/
 *   anchors/block-scalar fidelity nothing here needs, a much bigger
 *   dependency than this repo's own low-dependency precedent --
 *   `colorsys` over a color-math library, CLAUDE.md -- was willing to
 *   clear for a much smaller win). Now syntax-highlighted
 *   (`jsonHighlight.ts`, a small dependency-free regex tokenizer, not a
 *   real parser -- see that module's own docstring) via the standard
 *   highlighted-`<pre>`-behind-a-transparent-`<textarea>` trick, and
 *   validated live (`JSON.parse` on every keystroke, not only on Save)
 *   rather than only at Save time.
 *
 * `value` (the parsed document) is the single source of truth; the Raw
 * view's `text` is a derived, independently-edited string that only
 * syncs back into `value` when the view switches away from Raw (blocked
 * with an inline error if the current text doesn't parse) or on Apply --
 * this avoids re-parsing (and potentially clobbering `value` with
 * garbage) on every keystroke of an in-progress, momentarily-invalid
 * edit. Switching Form -> Raw re-serializes `value` into `text`.
 * Server-side `model_validate` (`app.py`'s `put_config`) remains the
 * authoritative validator regardless of which view is active -- neither
 * view attempts to replicate cross-field schema rules client-side.
 *
 * "Apply" (not "Save"): issue #24's deferred-save editor means `PUT
 * /api/config/{doc}` only ever updates the server's in-memory working
 * copy, never the file on disk -- this button's own local buffering
 * (still needed so an in-progress invalid Raw-view edit is never sent)
 * is a different, smaller thing than the app-wide Save in `App.tsx`'s
 * header, which is what actually flushes to disk. `dispatch({type:
 * "SET_DIRTY", ...})` from this button's own response is how that
 * header's Save button/close-warning learn about a Config-tab edit --
 * `usePlan`'s own mutations pick this up for free via `refetch()`
 * (`GET /api/plan` carries `dirty` too), but this component has no
 * `usePlan` access, so it dispatches directly. */
import { useEffect, useRef, useState } from "react";
import { ApiError, getConfig, getSchema, putConfig } from "../api/client";
import { highlightJson } from "../jsonHighlight";
import SchemaForm, { type JSONSchema } from "./SchemaForm";
import { useAppContext } from "../state/AppContext";
import type { ConfigDocName } from "../types";

const DOCS: ConfigDocName[] = ["design", "layouts", "presentation"];
type View = "form" | "raw";

export default function ConfigEditor() {
  const { dispatch } = useAppContext();
  const [doc, setDoc] = useState<ConfigDocName>("design");
  const [view, setView] = useState<View>("form");
  const [value, setValue] = useState<Record<string, unknown> | null>(null);
  const [schema, setSchema] = useState<JSONSchema | null>(null);
  const [text, setText] = useState("");
  const [rawError, setRawError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const preRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setRawError(null);
    Promise.all([getConfig(doc), getSchema(doc)])
      .then(([data, docSchema]) => {
        if (cancelled) return;
        setValue(data);
        setSchema(docSchema);
        setText(JSON.stringify(data, null, 2));
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [doc]);

  function handleRawChange(next: string) {
    setText(next);
    try {
      const parsed = JSON.parse(next);
      setRawError(null);
      setValue(parsed);
    } catch (err) {
      setRawError(err instanceof Error ? err.message : String(err));
    }
  }

  function switchView(next: View) {
    if (next === view) return;
    if (next === "form") {
      // Raw -> Form: block the switch on invalid JSON rather than
      // discarding the edit or handing the form a value that doesn't
      // match `text` anymore.
      if (rawError) return;
      setView("form");
      return;
    }
    // Form -> Raw: re-serialize the current (already-valid, since the
    // form only ever produces well-typed values) `value`.
    if (value !== null) setText(JSON.stringify(value, null, 2));
    setRawError(null);
    setView("raw");
  }

  function syncScroll() {
    if (!textareaRef.current || !preRef.current) return;
    preRef.current.scrollTop = textareaRef.current.scrollTop;
    preRef.current.scrollLeft = textareaRef.current.scrollLeft;
  }

  /** Applies the current edit to the server's in-memory working copy
   * (issue #24's deferred-save editor) -- not to disk. Kept as its own
   * explicit action, distinct from the app-wide Save in `App.tsx`'s
   * header, specifically for the Raw/JSON view: an in-progress invalid
   * edit must never be sent, so this still needs its own "commit when
   * I say so" boundary even though the disk write itself is deferred
   * further, to an explicit app-wide Save. */
  async function handleApply() {
    setError(null);
    if (view === "raw" && rawError) return;
    if (value === null) return;

    setSaving(true);
    try {
      const result = await putConfig(doc, value);
      dispatch({ type: "SET_DIRTY", dirty: result.dirty });
      setSavedAt(Date.now());
      // Refetch rather than trust the local edit verbatim -- the server
      // is the source of truth (e.g. `presentation.yaml` writes go
      // through `validate_presentation_data`, which may not be a
      // byte-identical echo of what was PUT).
      const fresh = await getConfig(doc);
      setValue(fresh);
      setText(JSON.stringify(fresh, null, 2));
      setRawError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="config-editor">
      <div className="config-editor__header">
        <label>
          Document
          <select value={doc} onChange={(e) => setDoc(e.target.value as ConfigDocName)}>
            {DOCS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        <div className="config-editor__view-toggle" role="group" aria-label="View">
          <button
            type="button"
            className={view === "form" ? "config-editor__view-btn--active" : undefined}
            onClick={() => switchView("form")}
          >
            Form
          </button>
          <button
            type="button"
            className={view === "raw" ? "config-editor__view-btn--active" : undefined}
            onClick={() => switchView("raw")}
          >
            Raw
          </button>
        </div>
        <p className="config-editor__note">
          {view === "form"
            ? "Typed fields generated from the document's own schema. Some values (e.g. colors' " +
              "derived-vs-literal entries) fall back to a small raw-JSON field this form can't " +
              "model generically."
            : "Editing as JSON (the API's own wire format) -- not the on-disk YAML syntax. " +
              "Comments and formatting in the YAML file itself aren't preserved."}
        </p>
      </div>

      {loading ? (
        <p>Loading…</p>
      ) : view === "form" ? (
        schema &&
        value !== null && (
          <div className="config-editor__form">
            <SchemaForm
              schema={schema}
              defs={(schema.$defs as Record<string, JSONSchema>) ?? {}}
              value={value}
              onChange={(next) => setValue(next as Record<string, unknown>)}
            />
          </div>
        )
      ) : (
        <div className="config-editor__raw-wrap">
          <pre
            ref={preRef}
            className="config-editor__raw-highlight"
            aria-hidden="true"
            dangerouslySetInnerHTML={{ __html: highlightJson(text) + "\n" }}
          />
          <textarea
            ref={textareaRef}
            className="config-editor__textarea config-editor__textarea--overlay"
            value={text}
            onChange={(e) => handleRawChange(e.target.value)}
            onScroll={syncScroll}
            spellCheck={false}
            rows={24}
          />
        </div>
      )}

      <div className="config-editor__actions">
        <button
          type="button"
          disabled={saving || loading || (view === "raw" && !!rawError)}
          onClick={() => void handleApply()}
        >
          {saving ? "Applying…" : "Apply"}
        </button>
        {savedAt && !error && (
          <span className="config-editor__saved">
            Applied to this session -- use the header's Save to write it to disk.
          </span>
        )}
      </div>

      {view === "raw" && rawError && (
        <pre className="config-editor__error" role="alert">
          invalid JSON: {rawError}
        </pre>
      )}
      {error && (
        <pre className="config-editor__error" role="alert">
          {error}
        </pre>
      )}
    </div>
  );
}
