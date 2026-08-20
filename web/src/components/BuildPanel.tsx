/**
 * Triggers a build (`POST /api/build`) or a preview render
 * (`POST /api/preview`, issue #27), polls `GET /api/jobs/{id}` via
 * `api/client.ts`'s `pollJobUntilDone` (bounded -- see that function's
 * own docstring for why it doesn't poll forever), and shows the result:
 * warning count, and artifact download links. `<a href={jobArtifactUrl(...)}>`
 * is a plain same-origin GET download, no special handling needed (this
 * isn't a Claude Artifact's sandboxed viewer -- the download-link
 * restriction that applies there doesn't apply to this app).
 *
 * Issue #27 also adds: an editable `build.output` path (PUT the whole
 * `presentation.yaml` back on blur, same pattern `DeckOptions.tsx`
 * already uses for its own inline fields), a proactive LibreOffice-
 * availability check (`GET /api/preview/availability`) shown *before*
 * Preview is even clickable rather than only as an error after a failed
 * attempt, an indeterminate progress bar while a job is queued/running
 * (the backend reports no real percentage, so this is honest about
 * that -- see `ProgressBar`), and, once a preview job succeeds, a grid
 * of per-slide PNGs plus an embedded `<iframe>` PDF viewer (the
 * browser's own built-in PDF viewer, no new dependency) whenever the
 * job's artifacts include a `pdf` key.
 *
 * Issue #32 adds: `OutputPathBrowser` next to the output-path input (a
 * real directory-browsing "file select" instead of a bare text field), a
 * "Render slide previews with this build" checkbox bound to
 * `presentation.yaml`'s `build.previews` (an ordinary `deckifyr build`
 * now also keeps the PDF it already produces internally once that's on,
 * mirroring `deckifyr preview`'s own reasoning -- see `cli.py`'s
 * `_cmd_build`), and `PreviewGallery` -- shared by both the Build
 * section's own results and the Preview section below -- replacing the
 * inline images-grid/iframe blocks that used to live only in the latter.
 * The checkbox is disabled (with the same `AvailabilityWarning` the
 * Preview button already showed) whenever `GET /api/preview/availability`
 * reports LibreOffice is missing -- a real, initially-shipped gap this
 * fixes: `build.previews` existed in the schema long before this
 * checkbox did, but only this checkbox made "check it with no LibreOffice
 * installed" a one-click mistake instead of something only reachable by
 * hand-editing YAML. As defense in depth for whatever this proactive
 * check doesn't catch (a stale `availability` fetch, a direct CLI build
 * with `build.previews: true` and no web UI in front of it at all),
 * `deckifyr.pptx.compose.compose_and_write` itself now downgrades a
 * missing-LibreOffice failure to a build warning rather than losing the
 * whole build over an opportunistic feature -- see that function's own
 * comment.
 */
import { useEffect, useState } from "react";
import {
  ApiError,
  getConfig,
  getJobArtifacts,
  getPreviewAvailability,
  jobArtifactUrl,
  pollJobUntilDone,
  postBuild,
  postPreview,
  putConfig,
} from "../api/client";
import OutputPathBrowser from "./OutputPathBrowser";
import PreviewGallery from "./PreviewGallery";
import { useAppContext } from "../state/AppContext";
import type { ApiErrorBody, Job, JobStatus, PreviewAvailability } from "../types";

const POLL_TIMEOUT_MS = 5 * 60 * 1000;

/** Indeterminate only -- `Job` carries no progress percentage, just
 * `queued`/`running`/`succeeded`/`failed`, so this shows *that* a job
 * is in flight without pretending to know how far along it is. */
function ProgressBar({ status }: { status: JobStatus | "idle" }) {
  if (status !== "queued" && status !== "running") return null;
  return (
    <div className="build-panel__progress" role="progressbar" aria-label={`${status}…`}>
      <div className="build-panel__progress-bar" />
    </div>
  );
}

/** Shown wherever a LibreOffice-dependent action is offered while
 * `GET /api/preview/availability` reports it's missing -- issue #27's
 * Preview button originally had the only copy of this message; issue
 * #32's own "Render slide previews" checkbox reuses it verbatim rather
 * than a second, differently-worded warning, since it's the same
 * proactive-disable pattern for the same underlying dependency. */
function AvailabilityWarning({
  availability,
  subject,
}: {
  availability: PreviewAvailability;
  subject: string;
}) {
  return (
    <p className="build-panel__availability-warning" role="alert">
      {subject} requires {availability.display_name}, which isn&rsquo;t installed.{" "}
      {availability.install_url && (
        <a href={availability.install_url} target="_blank" rel="noreferrer">
          Install {availability.display_name}
        </a>
      )}
    </p>
  );
}

/** A failed job whose error carries `dependency` (a missing `soffice`/
 * `quarto` binary, `MissingDependencyError.to_dict()`) shows that
 * dependency's name/install link instead of the raw error text --
 * issue #27's "with information there if they don't [have the
 * binaries]", surfaced for a job failure the same way
 * `getPreviewAvailability`'s proactive check does before one even
 * starts. */
function JobErrorDisplay({ error }: { error: ApiErrorBody }) {
  if (error.dependency) {
    return (
      <p className="build-panel__error" role="alert">
        This requires {error.dependency.display_name}, which isn&rsquo;t installed.{" "}
        <a href={error.dependency.install_url} target="_blank" rel="noreferrer">
          Install {error.dependency.display_name}
        </a>
      </p>
    );
  }
  return (
    <pre className="build-panel__error" role="alert">
      {error.message ?? error.detail ?? JSON.stringify(error)}
    </pre>
  );
}

interface JobRunState {
  status: JobStatus | "idle";
  job: Job | null;
  artifacts: string[];
  error: string | null;
  timedOut: boolean;
}

const IDLE_JOB_STATE: JobRunState = {
  status: "idle",
  job: null,
  artifacts: [],
  error: null,
  timedOut: false,
};

/** Runs `submit()`, polls the returned job to completion (or the poll
 * budget), and fetches its artifact list on a terminal status -- shared
 * by the Build and Preview buttons below, which otherwise differ only
 * in what they submit. */
async function runJob(submit: () => Promise<{ job_id: string }>): Promise<JobRunState> {
  const { job_id } = await submit();
  const finished = await pollJobUntilDone(job_id, { timeoutMs: POLL_TIMEOUT_MS });
  if (finished.status === "succeeded" || finished.status === "failed") {
    const { artifacts } = await getJobArtifacts(job_id);
    return { status: finished.status, job: finished, artifacts, error: null, timedOut: false };
  }
  return { status: finished.status, job: finished, artifacts: [], error: null, timedOut: true };
}

export default function BuildPanel() {
  const { state, dispatch } = useAppContext();

  // --- output path (issue #27) ----------------------------------------
  const [outputDoc, setOutputDoc] = useState<Record<string, unknown> | null>(null);
  const [outputSaving, setOutputSaving] = useState(false);
  const [outputError, setOutputError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getConfig("presentation")
      .then((doc) => {
        if (!cancelled) setOutputDoc(doc);
      })
      .catch((err) => {
        if (!cancelled) setOutputError(err instanceof ApiError ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const outputBuild = (outputDoc?.build as Record<string, unknown> | undefined) ?? {};
  const outputValue = typeof outputBuild.output === "string" ? outputBuild.output : "";

  async function saveOutputPath(value: string) {
    if (!outputDoc || value === outputValue || value.trim() === "") return;
    const next = { ...outputDoc, build: { ...outputBuild, output: value } };
    setOutputSaving(true);
    try {
      const result = await putConfig("presentation", next);
      setOutputDoc(next);
      setOutputError(null);
      // `putConfig` only touches the server's working copy (issue #24) --
      // without this, the header's Save/Discard/dirty indicator would
      // have no way to know this edit happened at all.
      dispatch({ type: "SET_DIRTY", dirty: result.dirty });
    } catch (err) {
      setOutputError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setOutputSaving(false);
    }
  }

  // --- render previews with build (issue #32) ---------------------------
  const previewsEnabled = outputBuild.previews === true;

  async function handlePreviewsChange(checked: boolean) {
    if (!outputDoc) return;
    const next = { ...outputDoc, build: { ...outputBuild, previews: checked } };
    setOutputSaving(true);
    try {
      const result = await putConfig("presentation", next);
      setOutputDoc(next);
      setOutputError(null);
      dispatch({ type: "SET_DIRTY", dirty: result.dirty });
    } catch (err) {
      setOutputError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setOutputSaving(false);
    }
  }

  // --- preview availability (issue #27) -------------------------------
  const [availability, setAvailability] = useState<PreviewAvailability | null>(null);

  useEffect(() => {
    let cancelled = false;
    getPreviewAvailability()
      .then((data) => {
        if (!cancelled) setAvailability(data);
      })
      .catch(() => {
        // Best-effort -- Preview just stays enabled on failure; a real
        // attempt would surface the same missing-dependency error anyway.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // --- build job -------------------------------------------------------
  const [build, setBuild] = useState<JobRunState>(IDLE_JOB_STATE);

  async function handleBuild() {
    setBuild({ ...IDLE_JOB_STATE, status: "queued" });
    try {
      setBuild(await runJob(postBuild));
    } catch (err) {
      setBuild({ ...IDLE_JOB_STATE, error: err instanceof ApiError ? err.message : String(err) });
    }
  }

  // --- preview job (issue #27) -----------------------------------------
  const [preview, setPreview] = useState<JobRunState>(IDLE_JOB_STATE);
  const [slidesInput, setSlidesInput] = useState("");

  function parsedSlides(): number[] | undefined {
    const tokens = slidesInput
      .split(",")
      .map((s) => Number(s.trim()))
      .filter((n) => Number.isInteger(n) && n > 0);
    return tokens.length > 0 ? tokens : undefined;
  }

  async function handlePreview() {
    setPreview({ ...IDLE_JOB_STATE, status: "queued" });
    try {
      setPreview(await runJob(() => postPreview(parsedSlides())));
    } catch (err) {
      setPreview({ ...IDLE_JOB_STATE, error: err instanceof ApiError ? err.message : String(err) });
    }
  }

  const previewUnavailable = availability !== null && !availability.available;
  const previewJobId = preview.job?.id;
  // The gallery already presents preview-N/pdf artifacts; the plain
  // download-link list only needs to cover everything else (pptx,
  // manifest, ...).
  const otherBuildArtifacts = build.artifacts.filter(
    (key) => !key.startsWith("preview-") && key !== "pdf"
  );

  return (
    <div className="build-panel">
      <label className="build-panel__output">
        Output path
        <input
          key={outputValue}
          defaultValue={outputValue}
          disabled={outputSaving || !outputDoc}
          onBlur={(e) => void saveOutputPath(e.target.value)}
        />
      </label>
      <OutputPathBrowser
        currentValue={outputValue}
        onSelect={(path) => void saveOutputPath(path)}
        disabled={outputSaving || !outputDoc}
      />
      {outputError && (
        <p className="build-panel__error" role="alert">
          {outputError}
        </p>
      )}

      <label className="build-panel__previews-toggle">
        <input
          type="checkbox"
          checked={previewsEnabled}
          disabled={outputSaving || !outputDoc || previewUnavailable}
          onChange={(e) => void handlePreviewsChange(e.target.checked)}
        />
        Render slide previews (PNG + PDF) with this build
      </label>
      {availability && previewUnavailable && (
        <AvailabilityWarning availability={availability} subject="Rendering previews" />
      )}

      <button
        type="button"
        onClick={() => void handleBuild()}
        disabled={build.status === "running" || build.status === "queued" || state.dirty}
      >
        Build
      </button>
      <ProgressBar status={build.status} />
      {state.dirty && (
        // `POST /api/build` always shells out to a real `deckifyr build`
        // subprocess that reads straight from disk (issue #24's deferred-
        // save editor) -- it has no visibility into the in-memory working
        // copy, so building while dirty would silently produce a `.pptx`
        // from the last-*saved* state, ignoring in-progress edits. A hard
        // stop here beats that surprise.
        <p className="build-panel__dirty-warning">
          Save your changes before building -- the last saved version has unsaved edits.
        </p>
      )}

      {build.status !== "idle" && <p className="build-panel__status">Status: {build.status}</p>}
      {build.timedOut && (
        <p className="build-panel__timeout">
          Still running after {Math.round(POLL_TIMEOUT_MS / 1000)}s of polling -- check back
          later, the build may still finish server-side.
        </p>
      )}

      {build.job?.result && (
        <div className="build-panel__result">
          <p>Slides: {build.job.result.slide_count ?? "?"}</p>
          <p>Warnings: {build.job.result.warning_count ?? 0}</p>
        </div>
      )}

      {build.job?.error && <JobErrorDisplay error={build.job.error} />}
      {build.error && (
        <pre className="build-panel__error" role="alert">
          {build.error}
        </pre>
      )}

      {build.job && otherBuildArtifacts.length > 0 && (
        <ul className="build-panel__artifacts">
          {otherBuildArtifacts.map((key) => (
            <li key={key}>
              <a href={jobArtifactUrl(build.job!.id, key)} download>
                {key}
              </a>
            </li>
          ))}
        </ul>
      )}
      {build.job && <PreviewGallery jobId={build.job.id} artifacts={build.artifacts} />}

      <div className="build-panel__preview">
        <h3>Preview</h3>
        {availability && previewUnavailable && (
          <AvailabilityWarning availability={availability} subject="Preview" />
        )}
        <label>
          Slides to preview
          <input
            placeholder="e.g. 1,3 -- blank = all slides"
            value={slidesInput}
            onChange={(e) => setSlidesInput(e.target.value)}
            disabled={previewUnavailable}
          />
        </label>
        <button
          type="button"
          onClick={() => void handlePreview()}
          disabled={
            preview.status === "running" ||
            preview.status === "queued" ||
            state.dirty ||
            previewUnavailable
          }
        >
          Preview
        </button>
        <ProgressBar status={preview.status} />
        {preview.status !== "idle" && (
          <p className="build-panel__status">Status: {preview.status}</p>
        )}
        {preview.timedOut && (
          <p className="build-panel__timeout">
            Still running after {Math.round(POLL_TIMEOUT_MS / 1000)}s of polling -- check back
            later.
          </p>
        )}
        {preview.job?.error && <JobErrorDisplay error={preview.job.error} />}
        {preview.error && (
          <pre className="build-panel__error" role="alert">
            {preview.error}
          </pre>
        )}

        {previewJobId && <PreviewGallery jobId={previewJobId} artifacts={preview.artifacts} />}
      </div>
    </div>
  );
}
