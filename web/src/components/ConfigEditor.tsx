/**
 * A raw-text editor for one of `design.yaml`/`layouts.yaml`/
 * `presentation.yaml`, deliberately *not* a schema-driven form (that's
 * documented future scope, see the module note below).
 *
 * Displayed/edited as pretty-printed **JSON, not YAML** -- a deliberate
 * simplification, not an oversight. `GET /api/config/{doc}` already
 * returns the parsed document as JSON, and `PUT /api/config/{doc}`'s
 * body is a JSON dict too (`app.py`'s `put_config`) -- the wire
 * contract is JSON-native end to end, so a YAML stringify/parse
 * dependency (e.g. `js-yaml`) would only buy cosmetic parity with the
 * on-disk file's own syntax, not any functional need this editor
 * actually has. A real YAML round trip is also a much bigger surface
 * than this repo's own low-dependency precedent (`colorsys` over a
 * color-math library, CLAUDE.md) was willing to clear for a much
 * smaller win: YAML has to get comments, anchors, block scalars, and
 * quoting right, none of which this textarea needs to preserve since
 * the *filesystem* round trip already goes through `deckifyr.editor`'s
 * own plain-PyYAML `_write_yaml` (CLAUDE.md's own noted limitation:
 * comments aren't preserved through `get`/`set`/`slide` either). This
 * label says so explicitly rather than silently presenting JSON as if
 * it were the YAML source.
 *
 * FUTURE SCOPE (not built here): a schema-driven form generated from
 * `GET /api/schemas/{doc}`'s JSON Schema, so a user edits typed fields
 * instead of raw text. Explicitly out of scope for this slice.
 */
import { useEffect, useState } from "react";
import { ApiError, getConfig, putConfig } from "../api/client";
import type { ConfigDocName } from "../types";

const DOCS: ConfigDocName[] = ["design", "layouts", "presentation"];

export default function ConfigEditor() {
  const [doc, setDoc] = useState<ConfigDocName>("design");
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getConfig(doc)
      .then((data) => {
        if (cancelled) return;
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

  async function handleSave() {
    setError(null);
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(text);
    } catch (err) {
      setError(`invalid JSON: ${err instanceof Error ? err.message : String(err)}`);
      return;
    }

    setSaving(true);
    try {
      await putConfig(doc, parsed);
      setSavedAt(Date.now());
      // Refetch rather than trust the local edit verbatim -- the server
      // is the source of truth (e.g. `presentation.yaml` writes go
      // through `validate_and_write_presentation`, which may not be a
      // byte-identical echo of what was PUT).
      const fresh = await getConfig(doc);
      setText(JSON.stringify(fresh, null, 2));
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
        <p className="config-editor__note">
          Editing as JSON (the API's own wire format) -- not the on-disk YAML syntax. Comments
          and formatting in the YAML file itself aren't preserved.
        </p>
      </div>

      {loading ? (
        <p>Loading…</p>
      ) : (
        <textarea
          className="config-editor__textarea"
          value={text}
          onChange={(e) => setText(e.target.value)}
          spellCheck={false}
          rows={24}
        />
      )}

      <div className="config-editor__actions">
        <button type="button" disabled={saving || loading} onClick={() => void handleSave()}>
          {saving ? "Saving…" : "Save"}
        </button>
        {savedAt && !error && <span className="config-editor__saved">Saved.</span>}
      </div>

      {error && (
        <pre className="config-editor__error" role="alert">
          {error}
        </pre>
      )}
    </div>
  );
}
