/**
 * Shared gallery for a job's `preview-N`/`pdf` artifacts (issue #32) --
 * used by both the Build tab's own results (once `build.previews` makes
 * an ordinary build produce them) and the standalone Preview section, so
 * the two don't drift on how they present the same kind of output.
 *
 * PNG thumbnails are always visible, small by default; clicking one
 * toggles a single `expandedKey` so at most one is ever enlarged at a
 * time (clicking the expanded one again collapses it, clicking a
 * different one swaps which is expanded). The PDF is never fetched
 * unless the user actually asks for it: it sits behind a closed-by-
 * default `<details>` disclosure, and the `<iframe>` only mounts once
 * that's opened.
 */
import { useState } from "react";
import { jobArtifactUrl } from "../api/client";

export default function PreviewGallery({
  jobId,
  artifacts,
}: {
  jobId: string;
  artifacts: string[];
}) {
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  // React-controlled, not just the native `<details>` closed state --
  // a closed `<details>`'s children stay in the DOM (only visually
  // hidden), and a browser still fetches an `<iframe src=...>` that's
  // merely `display: none`. Only actually rendering the `<iframe>` once
  // `pdfOpen` is true is what makes "the PDF is never fetched unless
  // requested" true, not just "visually" true.
  // Toggled via the `<summary>`'s own click handler (below), not the
  // native "toggle" DOM event -- that event fires from a queued task per
  // the HTML spec, not synchronously with the click, which would make
  // both real usage and tests observe a one-tick-late render for no
  // benefit here.
  const [pdfOpen, setPdfOpen] = useState(false);

  const previewImageKeys = artifacts
    .filter((key) => key.startsWith("preview-"))
    .sort((a, b) => Number(a.slice("preview-".length)) - Number(b.slice("preview-".length)));
  const hasPdf = artifacts.includes("pdf");

  if (previewImageKeys.length === 0 && !hasPdf) return null;

  function toggleExpanded(key: string) {
    setExpandedKey((current) => (current === key ? null : key));
  }

  return (
    <div className="preview-gallery">
      {previewImageKeys.length > 0 && (
        <div className="preview-gallery__images">
          {previewImageKeys.map((key) => (
            <img
              key={key}
              src={jobArtifactUrl(jobId, key)}
              alt={key}
              tabIndex={0}
              className={
                expandedKey === key
                  ? "preview-gallery__image preview-gallery__image--expanded"
                  : "preview-gallery__image"
              }
              onClick={() => toggleExpanded(key)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  toggleExpanded(key);
                }
              }}
            />
          ))}
        </div>
      )}
      {hasPdf && (
        <details className="preview-gallery__pdf" open={pdfOpen}>
          <summary
            onClick={(e) => {
              e.preventDefault();
              setPdfOpen((v) => !v);
            }}
          >
            Show PDF preview
          </summary>
          {pdfOpen && (
            <iframe
              className="preview-gallery__pdf-viewer"
              title="Preview PDF"
              src={jobArtifactUrl(jobId, "pdf")}
            />
          )}
        </details>
      )}
    </div>
  );
}
