/**
 * Triggers a build (`POST /api/build`), polls `GET /api/jobs/{id}` via
 * `api/client.ts`'s `pollJobUntilDone` (bounded -- see that function's
 * own docstring for why it doesn't poll forever), and shows the result:
 * warning count, and artifact download links. `<a href={jobArtifactUrl(...)}>`
 * is a plain same-origin GET download, no special handling needed (this
 * isn't a Claude Artifact's sandboxed viewer -- the download-link
 * restriction that applies there doesn't apply to this app).
 */
import { useState } from "react";
import { ApiError, getJobArtifacts, jobArtifactUrl, pollJobUntilDone, postBuild } from "../api/client";
import { useAppContext } from "../state/AppContext";
import type { Job, JobStatus } from "../types";

const POLL_TIMEOUT_MS = 5 * 60 * 1000;

export default function BuildPanel() {
  const { state } = useAppContext();
  const [status, setStatus] = useState<JobStatus | "idle">("idle");
  const [job, setJob] = useState<Job | null>(null);
  const [artifacts, setArtifacts] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [timedOut, setTimedOut] = useState(false);

  async function handleBuild() {
    setError(null);
    setTimedOut(false);
    setArtifacts([]);
    setJob(null);
    setStatus("queued");
    try {
      const { job_id } = await postBuild();
      const finished = await pollJobUntilDone(job_id, { timeoutMs: POLL_TIMEOUT_MS });
      setJob(finished);
      setStatus(finished.status);
      if (finished.status === "succeeded" || finished.status === "failed") {
        const { artifacts: keys } = await getJobArtifacts(job_id);
        setArtifacts(keys);
      } else {
        // Still running/queued after the poll budget -- surface "still
        // running" rather than silently spinning forever.
        setTimedOut(true);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setStatus("idle");
    }
  }

  return (
    <div className="build-panel">
      <button
        type="button"
        onClick={() => void handleBuild()}
        disabled={status === "running" || status === "queued" || state.dirty}
      >
        Build
      </button>
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

      {status !== "idle" && <p className="build-panel__status">Status: {status}</p>}
      {timedOut && (
        <p className="build-panel__timeout">
          Still running after {Math.round(POLL_TIMEOUT_MS / 1000)}s of polling -- check back
          later, the build may still finish server-side.
        </p>
      )}

      {job?.result && (
        <div className="build-panel__result">
          <p>Slides: {job.result.slide_count ?? "?"}</p>
          <p>Warnings: {job.result.warning_count ?? 0}</p>
        </div>
      )}

      {job?.error && (
        <pre className="build-panel__error" role="alert">
          {job.error.message ?? job.error.detail ?? JSON.stringify(job.error)}
        </pre>
      )}

      {error && (
        <pre className="build-panel__error" role="alert">
          {error}
        </pre>
      )}

      {job && artifacts.length > 0 && (
        <ul className="build-panel__artifacts">
          {artifacts.map((key) => (
            <li key={key}>
              <a href={jobArtifactUrl(job.id, key)} download>
                {key}
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
