/**
 * The deck-wide (not per-slide) toggles a user is most likely to reach
 * for: `presentation.yaml`'s top-level `status_indicator` field (spec
 * section 7.8) -- the actual on/off switch for the watermark/status
 * furniture placement `SlideCanvas` now renders as fixed, non-draggable
 * content (see that file's own `FURNITURE_PREFIX` comment) -- plus the
 * two text sources that field's chosen placement actually displays:
 * `metadata.status` (the deck's own descriptive status word -- "demo",
 * "draft", "final", ...) and `watermark` (an optional, rarely-needed
 * override when the mark itself should say something *different* from
 * `metadata.status`). Reads/writes the full `presentation.yaml`
 * document through the same `GET`/`PUT /api/config/presentation`
 * endpoints `ConfigEditor` uses, mutating only these fields and leaving
 * everything else in the document untouched.
 *
 * "Deck status" (`metadata.status`), not "watermark text", is the
 * primary input: `deckifyr.plan.resolve_watermark_text` uses
 * `watermark ?? metadata.status`, so this one field is what actually
 * feeds *any* placement -- a corner as much as the full-page watermark
 * -- and it's already meaningful even with `status_indicator: none`
 * (plain descriptive metadata). The earlier version of this component
 * only exposed the `watermark` override, labeled generically "Text" --
 * confusing for a corner placement (nothing here is a "watermark" in
 * that case) and for the common case of just wanting to set the deck's
 * status once. A real user hit this confusion directly.
 *
 * Deliberately narrow: `design.yaml`'s other furniture blocks
 * (`background`/`branding`/`page_number`) are enabled by the *presence*
 * of a whole sub-object (box/style/etc), not a boolean, so there's no
 * honest single toggle for them without a real schema-aware form --
 * out of scope here the same way `ConfigEditor` itself stays a raw JSON
 * textarea rather than a schema-driven form (see its own module
 * comment). Those remain editable only via the Config tab.
 *
 * `onSaved` (optional): called after a successful PUT. This component
 * does its own independent `GET`/`PUT /api/config/presentation` fetch
 * rather than going through `usePlan`, so without this callback a
 * change here (status_indicator, or the watermark text -- both directly
 * affect the furniture pseudo-slide's `__furniture_status` element,
 * issue #21) never reaches `usePlan`'s own cached `slides`/
 * `furnitureSlide` -- confirmed the confusing way: the canvas kept
 * showing the *previous* watermark text until some unrelated action
 * happened to trigger `usePlan.refetch()` (e.g. dragging an element).
 * `App.tsx`'s `EditorTab` wires this to `plan.refetch`.
 */
import { useEffect, useState } from "react";
import { ApiError, getConfig, putConfig } from "../api/client";

interface Props {
  onSaved?: () => void;
}

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

export default function DeckOptions({ onSaved }: Props) {
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
      onSaved?.();
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
  const metadata = (doc.metadata as Record<string, unknown>) ?? {};
  const deckStatus = typeof metadata.status === "string" ? metadata.status : "";
  const watermarkOverride = typeof doc.watermark === "string" ? doc.watermark : "";

  return (
    <div className="deck-options">
      <span className="deck-options__label">Deck-wide:</span>
      <label>
        Deck status
        <input
          defaultValue={deckStatus}
          disabled={saving}
          placeholder="e.g. demo, draft, final"
          onBlur={(e) => {
            const value = e.target.value;
            if (value === deckStatus) return;
            void save({ metadata: { ...metadata, status: value === "" ? null : value } });
          }}
        />
      </label>
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
          Watermark override
          <input
            defaultValue={watermarkOverride}
            disabled={saving}
            placeholder={deckStatus ? `(falls back to "${deckStatus}" above)` : "(falls back to Deck status above)"}
            onBlur={(e) => {
              const value = e.target.value;
              if (value === watermarkOverride) return;
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
