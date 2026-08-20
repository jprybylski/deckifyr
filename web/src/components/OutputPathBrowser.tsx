/**
 * A small popover for picking `build.output` (issue #32) -- lets an
 * author navigate the project's real directory structure instead of
 * hand-typing a project-relative path, while still recognizing the
 * target `.pptx` itself doesn't exist yet (there's no "open" step, only
 * a directory to land in and a filename to type).
 *
 * Deliberately not a native OS file dialog: this is a local web app
 * whose server owns the project root and writes a project-relative
 * string into `presentation.yaml`, not an arbitrary filesystem path a
 * browser's own save dialog would hand back. `browseProject` (see its
 * own doc comment in `api/client.ts`) is called once per directory the
 * user actually clicks into -- never the whole tree up front -- so a
 * project with a deep, unrelated directory tree (a populated
 * `renv/library`, `node_modules`, ...) is never walked as a whole just
 * because this panel was opened.
 */
import { useEffect, useState } from "react";
import { ApiError, browseProject } from "../api/client";
import type { ProjectBrowseResponse } from "../types";

function dirname(path: string): string {
  const idx = path.lastIndexOf("/");
  return idx === -1 ? "" : path.slice(0, idx);
}

function basename(path: string): string {
  const idx = path.lastIndexOf("/");
  return idx === -1 ? path : path.slice(idx + 1);
}

function joinPath(dir: string, filename: string): string {
  return dir ? `${dir}/${filename}` : filename;
}

export default function OutputPathBrowser({
  currentValue,
  onSelect,
  disabled,
}: {
  currentValue: string;
  onSelect: (path: string) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [dir, setDir] = useState("");
  const [listing, setListing] = useState<ProjectBrowseResponse | null>(null);
  const [filename, setFilename] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleOpen() {
    setFilename(basename(currentValue) || "deck.pptx");
    setDir(dirname(currentValue));
    setOpen(true);
  }

  // The single fetch point -- every navigation (opening the panel, a
  // folder row, "..") only ever changes `dir`/`open`; this effect is what
  // actually issues the (single-level, never-recursive) request for
  // whichever directory that leaves us in.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    browseProject(dir)
      .then((data) => {
        if (!cancelled) setListing(data);
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
  }, [open, dir]);

  function handleUse() {
    const trimmed = filename.trim();
    if (!trimmed) return;
    onSelect(joinPath(dir, trimmed));
    setOpen(false);
  }

  if (!open) {
    return (
      <button
        type="button"
        className="output-path-browser__toggle"
        onClick={handleOpen}
        disabled={disabled}
      >
        Browse…
      </button>
    );
  }

  return (
    <div className="output-path-browser">
      <div className="output-path-browser__path">/{dir}</div>
      {loading && <p className="output-path-browser__status">Loading…</p>}
      {error && (
        <p className="output-path-browser__error" role="alert">
          {error}
        </p>
      )}
      {listing && (
        <ul className="output-path-browser__listing">
          {dir !== "" && (
            <li>
              <button type="button" onClick={() => setDir(dirname(dir))}>
                .. (up)
              </button>
            </li>
          )}
          {listing.dirs.map((name) => (
            <li key={`dir-${name}`}>
              <button type="button" onClick={() => setDir(joinPath(dir, name))}>
                📁 {name}
              </button>
            </li>
          ))}
          {listing.files.map((name) => (
            <li key={`file-${name}`} className="output-path-browser__file">
              {name}
            </li>
          ))}
          {listing.truncated && (
            <li className="output-path-browser__truncated">
              Showing the first {listing.dirs.length + listing.files.length} entries -- type a
              subdirectory name directly if it isn&rsquo;t listed.
            </li>
          )}
        </ul>
      )}
      <label className="output-path-browser__filename">
        Filename
        <input value={filename} onChange={(e) => setFilename(e.target.value)} />
      </label>
      <div className="output-path-browser__actions">
        <button type="button" onClick={handleUse} disabled={!filename.trim()}>
          Use this path
        </button>
        <button type="button" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </div>
  );
}
