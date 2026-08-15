/**
 * The deck-wide (not per-slide) toggles a user is most likely to reach
 * for: `presentation.yaml`'s top-level `status_indicator`/`watermark`
 * fields (spec section 7.8) -- the actual on/off switch for the
 * watermark/status furniture placement `SlideCanvas` now renders as
 * fixed, non-draggable content (see that file's own `FURNITURE_PREFIX`
 * comment). Reads/writes the full `presentation.yaml` document through
 * the same `GET`/`PUT /api/config/presentation` endpoints
 * `ConfigEditor` uses, mutating only these two fields and leaving
 * everything else in the document untouched.
 *
 * Deliberately narrow: `design.yaml`'s other furniture blocks
 * (`background`/`branding`/`page_number`) are enabled by the *presence*
 * of a whole sub-object (box/style/etc), not a boolean, so there's no
 * honest single toggle for them without a real schema-aware form --
 * out of scope here the same way `ConfigEditor` itself stays a raw JSON
 * textarea rather than a schema-driven form (see its own module
 * comment). Those remain editable only via the Config tab.
 */
import { useEffect, useState } from "react";
import { ApiError, getConfig, putConfig } from "../api/client";

type StatusIndicatorMode =
  | "none"
  | "watermark"
  | "corner-tr"
  | "corner-tl"
  | "corner-bl"
  | "corner-br";

const STATUS_INDICATOR_OPTIONS: Array<{ value: StatusIndicatorMode; label: string }> = [
  { value: "none", label: "None" },
  { value: "watermark", label: "Watermark (full-slide, diagonal)" },
  { value: "corner-tr", label: "Corner: top-right" },
  { value: "corner-tl", label: "Corner: top-left" },
  { value: "corner-bl", label: "Corner: bottom-left" },
  { value: "corner-br", label: "Corner: bottom-right" },
];

export default function DeckOptions() {
  const [doc, setDoc] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getConfig("presentation")
      .then((data) => {
        if (!cancelled) setDoc(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function save(patch: Record<string, unknown>) {
    if (!doc) return;
    const next = { ...doc, ...patch };
    setSaving(true);
    try {
      await putConfig("presentation", next);
      setDoc(next);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return null;
  if (!doc) {
    return error ? (
      <div className="deck-options deck-options__error" role="alert">
        {error}
      </div>
    ) : null;
  }

  const statusIndicator = (doc.status_indicator as StatusIndicatorMode | null) ?? "none";
  const watermarkText = typeof doc.watermark === "string" ? doc.watermark : "";

  return (
    <div className="deck-options">
      <span className="deck-options__label">Deck-wide:</span>
      <label>
        Status/watermark
        <select
          value={statusIndicator}
          disabled={saving}
          onChange={(e) => {
            const value = e.target.value as StatusIndicatorMode;
            void save({ status_indicator: value === "none" ? null : value });
          }}
        >
          {STATUS_INDICATOR_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>
      {statusIndicator !== "none" && (
        <label>
          Text
          <input
            defaultValue={watermarkText}
            disabled={saving}
            placeholder="(falls back to metadata.status)"
            onBlur={(e) => {
              const value = e.target.value;
              if (value === watermarkText) return;
              void save({ watermark: value === "" ? null : value });
            }}
          />
        </label>
      )}
      {error && (
        <span className="deck-options__error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
