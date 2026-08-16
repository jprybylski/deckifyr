/**
 * The deck-wide (not per-slide) toggles a user is most likely to reach
 * for: `presentation.yaml`'s top-level `status_indicator` field (spec
 * section 7.8) -- a strict single-select between no indicator, a
 * full-page watermark, or one of four corner placements. Plus the two
 * text sources whichever placement shows: `metadata.status` (the deck's
 * own descriptive status word -- "demo", "draft", "final", ...) and
 * `watermark` (an optional, rarely-needed override when the mark should
 * say something *different* from `metadata.status`). Reads/writes the
 * full `presentation.yaml` document through the same `GET`/`PUT
 * /api/config/presentation` endpoints `ConfigEditor` uses, mutating only
 * these fields and leaving everything else in the document untouched.
 *
 * issue #24 briefly added a separate, additive `watermark_overlay`
 * boolean (a "Show watermark" checkbox here) so a corner and the full
 * watermark could render at the same time -- reverted after dogfeeding:
 * the checkbox turned out to be functionally identical to
 * `FurnitureControls`' own "Add" button for the same element whenever it
 * turned the watermark *on*, and diverged from "Remove" in a way that
 * wasn't visible from either control (the checkbox only flipped the
 * activation flag, "Remove" deleted the underlying `design.yaml` style
 * outright) -- two controls in two different panels quietly doing
 * different things under the same "watermark" label. See
 * `deckifyr.plan.FURNITURE_STATUS_ID`'s own docstring for the fuller
 * reasoning.
 *
 * "Deck status" (`metadata.status`) is the primary input for *every*
 * placement, corner or full watermark, and it's already meaningful even
 * with `status_indicator: none` (plain descriptive metadata). "Watermark
 * override" is always visible too (an earlier version of this fix hid it
 * whenever `status_indicator` wasn't `"watermark"`, which then hid the
 * one field needed to set it up *before* switching to that placement --
 * a real, reported regression), but it only actually *does* anything for
 * the full-page `"watermark"` placement itself: `deckifyr.plan
 * .resolve_watermark_text` deliberately does *not* use `watermark ??
 * metadata.status` for a corner placement, only for `"watermark"`. The
 * inline hint shown when `status_indicator === "watermark"` and this
 * field is non-empty exists specifically because a real user set both
 * Deck status ("demo") and Watermark override ("test") expecting the
 * watermark to still show Deck status somewhere, and only discovered the
 * override wins after adding it and finding different text than
 * expected -- surfacing the precedence up front instead of leaving it
 * implicit. The earlier version of this component only exposed the
 * override, labeled generically "Text" -- confusing for a corner
 * placement in a different way (nothing there read as "a watermark" at
 * all) and for the common case of just wanting to set the deck's status
 * once. A real user hit that confusion too.
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
import { addFurnitureElement, ApiError, getConfig, putConfig } from "../api/client";

interface Props {
  onSaved?: () => void;
}

// Mirrors `FurnitureControls.tsx`'s own literal (see that file's own
// comment on why it isn't imported from a shared constants module).
const FURNITURE_STATUS_ID = "__furniture_status";

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

  async function save(patch: Record<string, unknown>): Promise<boolean> {
    if (!doc) return false;
    const next = { ...doc, ...patch };
    setSaving(true);
    try {
      await putConfig("presentation", next);
      setDoc(next);
      setError(null);
      onSaved?.();
      return true;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      return false;
    } finally {
      setSaving(false);
    }
  }

  /** Selecting a placement from the Status indicator dropdown must never
   * leave the deck half-configured -- the dropdown presents every
   * placement as a normal, always-selectable option, so picking one has
   * to always result in something that actually renders. A real user
   * hit exactly this: picking a fresh corner immediately 422'd the real
   * slide canvas ("furniture.status has no 'corner_tl' configured"),
   * which reads as a crash on an ordinary, allowed action, not a
   * deliberate strictness policy -- because from the dropdown's own
   * point of view, it wasn't an invalid choice. This materializes a
   * default style the same way `FurnitureControls`' own "Add" button
   * does (`POST /api/furniture/elements/__furniture_status`), right
   * after selecting -- so selecting and configuring collapse into one
   * action instead of two. "Already configured" (422 -- an earlier
   * session left a style here, e.g. after switching away and back) is
   * the only way this specific call can fail immediately after a
   * successful select, so it's swallowed rather than surfaced; any other
   * failure is a real error and still shown. */
  async function selectStatusIndicator(value: StatusIndicatorMode) {
    const ok = await save({ status_indicator: value === "none" ? null : value });
    if (!ok || value === "none") return;
    try {
      await addFurnitureElement(FURNITURE_STATUS_ID);
      onSaved?.();
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) return;
      setError(err instanceof ApiError ? err.message : String(err));
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
  const watermarkActive = statusIndicator === "watermark";

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
        Status indicator
        <select
          value={statusIndicator}
          disabled={saving}
          onChange={(e) => void selectStatusIndicator(e.target.value as StatusIndicatorMode)}
        >
          {STATUS_INDICATOR_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>
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
      {watermarkActive && watermarkOverride !== "" && (
        // This field is always editable (it's just inert text sitting in
        // presentation.yaml otherwise), but it only actually *does*
        // anything for the full-page `"watermark"` placement -- a corner
        // always shows Deck status verbatim (`resolve_watermark_text`'s
        // own docstring). Surfaced here rather than left implicit: a real
        // user set both fields expecting the watermark to still show
        // Deck status somewhere, and only discovered the override wins
        // after adding it and finding different text than expected.
        <span className="deck-options__hint" role="status">
          Note: this override replaces Deck status in the watermark overlay specifically
          (not the corner status indicator, which always shows Deck status) --
          &quot;{deckStatus || "(unset)"}&quot; won&rsquo;t be shown there.
        </span>
      )}
      {error && (
        <span className="deck-options__error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
