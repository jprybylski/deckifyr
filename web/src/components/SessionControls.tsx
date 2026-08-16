/**
 * App-wide Save/Discard/autosave controls for issue #24's deferred-save
 * editor. Lives in `App.tsx`'s header -- visible across all three tabs,
 * not `Toolbar.tsx` (Editor-tab-only) -- since a Config-tab edit needs
 * the same Save/Discard/close-warning as an element drag does.
 * `state.dirty` (`AppContext`) is the single shared source of truth this
 * reads; `postSave`/`postDiscard` (`api/client.ts`) are the only two
 * calls anywhere in the frontend that ever change what's on disk -- every
 * other mutation (`patchElement`, `putConfig`, the furniture routes)
 * only ever touches the server's in-memory working copy.
 */
import { useEffect, useRef, useState } from "react";
import { ApiError, getConfig, postDiscard, postSave, putConfig } from "../api/client";
import { useAppContext } from "../state/AppContext";

export default function SessionControls() {
  const { state, dispatch } = useAppContext();
  const [autosave, setAutosave] = useState(false);
  const [saving, setSaving] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Mirrors state.dirty for the `beforeunload` handler below. A plain
  // `dispatch` alone isn't enough in `handleDiscard`: dispatch only
  // *schedules* a re-render, it doesn't synchronously update the
  // `state.dirty` this component's closures see, but
  // `window.location.reload()` right after it runs immediately, in the
  // same synchronous tick -- so the `beforeunload` listener below would
  // still observe the stale `dirty: true` at that instant and fire a
  // real, unnecessary "leave site?" confirmation on every Discard click.
  // Confirmed with a real Playwright/Chromium run (not just reasoned
  // about): `page.on("dialog")` observed a genuine `beforeunload` dialog
  // fire immediately after a successful `POST /api/discard`, with the
  // plain-dispatch version of this fix in place. A ref sidesteps React's
  // render timing entirely: it's updated in place, so setting it right
  // before `reload()` is visible to the very next `beforeunload` check
  // no matter when that fires.
  const dirtyRef = useRef(state.dirty);
  useEffect(() => {
    dirtyRef.current = state.dirty;
  }, [state.dirty]);

  useEffect(() => {
    let cancelled = false;
    getConfig("presentation")
      .then((doc) => {
        if (cancelled) return;
        const build = (doc.build as Record<string, unknown> | undefined) ?? {};
        setAutosave(Boolean(build.autosave));
      })
      .catch(() => {
        // Best-effort -- the checkbox just stays unchecked on failure;
        // Save/Discard themselves don't depend on this fetch succeeding.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // The close warning (issue #24): fires only while something is
  // actually unsaved, standard `beforeunload` pattern.
  useEffect(() => {
    function handleBeforeUnload(event: BeforeUnloadEvent) {
      if (!dirtyRef.current) return;
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, []);

  async function handleSave() {
    setError(null);
    setSaving(true);
    try {
      await postSave();
      dispatch({ type: "SET_DIRTY", dirty: false });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function handleDiscard() {
    setError(null);
    setDiscarding(true);
    try {
      await postDiscard();
      // Clear dirty state before reloading -- see dirtyRef's own comment
      // above for why this must be the ref write, not just the dispatch
      // (kept below too, so anything that renders before the reload
      // actually completes reflects the true state as well).
      dirtyRef.current = false;
      dispatch({ type: "SET_DIRTY", dirty: false });
      // Simplest correct way to resync every independently-fetched piece
      // of state (`usePlan`'s slides, `ConfigEditor`'s loaded doc,
      // `DeckOptions`' doc) without threading a refetch callback through
      // all of them -- Discard should be rare enough that a reload's
      // brief flash is an acceptable cost for the simplicity.
      window.location.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setDiscarding(false);
    }
  }

  async function handleAutosaveChange(checked: boolean) {
    setError(null);
    try {
      const doc = await getConfig("presentation");
      const build = (doc.build as Record<string, unknown> | undefined) ?? {};
      const result = await putConfig("presentation", {
        ...doc,
        build: { ...build, autosave: checked },
      });
      setAutosave(checked);
      // Turning autosave on flushes immediately server-side (`app.py`'s
      // `_after_mutation`), so `result.dirty` is already back to `false`
      // in that case; turning it off just leaves the usual dirty state.
      dispatch({ type: "SET_DIRTY", dirty: result.dirty });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  return (
    <div className="session-controls">
      <label className="session-controls__autosave">
        <input
          type="checkbox"
          checked={autosave}
          onChange={(e) => void handleAutosaveChange(e.target.checked)}
        />
        Autosave
      </label>
      <span
        className={
          state.dirty
            ? "session-controls__status session-controls__status--dirty"
            : "session-controls__status"
        }
      >
        {state.dirty ? "Unsaved changes" : "All changes saved"}
      </span>
      <button type="button" disabled={!state.dirty || saving} onClick={() => void handleSave()}>
        {saving ? "Saving…" : "Save"}
      </button>
      <button
        type="button"
        disabled={!state.dirty || discarding}
        onClick={() => void handleDiscard()}
      >
        {discarding ? "Discarding…" : "Discard"}
      </button>
      {error && (
        <span className="session-controls__error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
