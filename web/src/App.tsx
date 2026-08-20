import { useEffect, useState } from "react";
import { AppProvider } from "./state/AppContext";
import { usePlan } from "./state/usePlan";
import { ApiError, getHealth, getProject } from "./api/client";
import type { Launcher } from "./types";
import SlideCanvas from "./components/SlideCanvas";
import SlideList from "./components/SlideList";
import ElementList from "./components/ElementList";
import Toolbar from "./components/Toolbar";
import DeckOptions from "./components/DeckOptions";
import ConfigEditor from "./components/ConfigEditor";
import BuildPanel from "./components/BuildPanel";
import SessionControls from "./components/SessionControls";
import "./App.css";

type Tab = "editor" | "config" | "build";

function EditorTab() {
  // `usePlan` is called once here (not inside SlideCanvas itself) so
  // SlideList/Toolbar/ElementList all see the same fetched slide list
  // and share one set of undo/redo history bookkeeping instead of each
  // firing its own `/api/plan` request -- see `state/usePlan.ts`'s own
  // module docstring for the fuller rationale.
  const plan = usePlan();
  // `DeckOptions` fetches `presentation.yaml` once on mount and only
  // ever updates its own local copy from its own saves -- it has no way
  // to learn that `ElementList`'s furniture Add (status-indicator
  // redesign note: `deckifyr.plan.FURNITURE_STATUS_ID`'s own docstring)
  // just changed `status_indicator` server-side out from under it.
  // Confirmed the real way, not assumed: an e2e test clicking Add in the
  // Furniture panel left the Deck Options dropdown still showing "None"
  // until something else happened to remount it. Bumping this key
  // forces a clean remount (and therefore a fresh fetch) the same way
  // `onSaved` already keeps `usePlan` in sync in the other direction.
  const [deckOptionsKey, setDeckOptionsKey] = useState(0);
  const refreshDeckOptions = () => setDeckOptionsKey((k) => k + 1);
  return (
    <div className="editor-layout">
      <Toolbar plan={plan} />
      <DeckOptions key={deckOptionsKey} onSaved={plan.refetch} />
      <div className="editor-layout__body">
        <SlideList plan={plan} />
        <SlideCanvas plan={plan} />
        <ElementList plan={plan} onStatusIndicatorChanged={refreshDeckOptions} />
      </div>
    </div>
  );
}

type ProjectStatus =
  | { state: "checking" }
  | { state: "ready"; root: string }
  | { state: "error"; message: string; launcher: Launcher | null };

/**
 * Gates the whole editor UI behind one `GET /api/project` check (which
 * itself fails whenever `presentation.yaml`/`design.yaml`/`layouts.yaml`
 * can't be loaded, per `app.py`'s `_project_paths()`) so a `deckifyr
 * serve` started outside a real project shows one clear, minimal
 * message instead of the tabs/toolbar/three-panel editor rendering
 * anyway with each panel independently hitting (and displaying) its own
 * copy of the same underlying fetch failure -- confirmed as the actual
 * failure mode by screenshotting an unfixed build against an empty
 * directory before writing this gate.
 *
 * Also fetches `GET /api/health` for its `launcher` field ("cli" or
 * "r", `cli.py`'s `serve --launcher`/`R/serve.R`'s `deck_serve()`) --
 * `/api/health` is used specifically because it (unlike `/api/project`)
 * never depends on the bound project actually loading, so it's the one
 * route this "no project" screen can rely on to know whether to show
 * `deckifyr`-CLI or R-facade next-step instructions. A failed health
 * fetch (the server itself unreachable, not just "no project") falls
 * back to `null`, which `NoProjectScreen` treats as "show both" rather
 * than guessing wrong.
 */
/** `frontendWarning` rides on the same `/api/health` fetch this hook
 * already does for `launcher` -- `deckifyr.web.app._frontend_build_
 * warning`'s own docstring has the full "why": a real incident where a
 * genuine source fix sat uncompiled while a live `deckifyr serve`
 * session kept serving the old, pre-fix JS, and a browser hard-refresh
 * alone didn't help (confusing, since `StaticFiles` really was serving
 * fresh bytes -- just still the stale ones). Surfacing it here, in the
 * one place every tab's header renders, means it's visible no matter
 * which tab is open, not just on first load. */
function useProjectStatus(): { status: ProjectStatus; frontendWarning: string | null } {
  const [status, setStatus] = useState<ProjectStatus>({ state: "checking" });
  const [frontendWarning, setFrontendWarning] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      let launcher: Launcher | null = null;
      try {
        const health = await getHealth();
        launcher = health.launcher;
        if (!cancelled) setFrontendWarning(health.frontend_warning);
      } catch {
        // Handled by the /api/project try/catch below either way -- a
        // health-fetch failure just means NoProjectScreen falls back to
        // showing both CLI and R instructions instead of guessing.
      }
      try {
        const info = await getProject();
        if (!cancelled) setStatus({ state: "ready", root: info.root });
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof ApiError ? err.message : String(err);
        setStatus({ state: "error", message, launcher });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return { status, frontendWarning };
}

function NoProjectScreen({ message, launcher }: { message: string; launcher: Launcher | null }) {
  const showCli = launcher !== "r";
  const showR = launcher !== "cli";
  const bothShown = showCli && showR;
  return (
    <div className="no-project">
      <h1>
        <img src="/logo.png" alt="" className="no-project__logo" />
        deckifyr
      </h1>
      <p className="no-project__message">{message}</p>
      <p>
        This directory doesn&rsquo;t look like a deckifyr project. Either:
      </p>
      {showR && (
        <>
          {bothShown && <p className="no-project__via">Using R:</p>}
          <ul>
            <li>
              run <code>initialize_deck_project(&quot;&lt;directory&gt;&quot;)</code> to scaffold a
              new project, then restart{" "}
              <code>deck_serve(project = &quot;&lt;directory&gt;&quot;)</code> pointed at it, or
            </li>
            <li>
              restart <code>deck_serve(project = &quot;&lt;directory&gt;&quot;)</code> pointed at
              an existing project directory (one containing <code>presentation.yaml</code>).
            </li>
          </ul>
        </>
      )}
      {showCli && (
        <>
          {bothShown && <p className="no-project__via">Using the CLI:</p>}
          <ul>
            <li>
              run <code>deckifyr init &lt;directory&gt;</code> to scaffold a new project, then
              restart <code>deckifyr serve --project &lt;directory&gt;</code> pointed at it, or
            </li>
            <li>
              restart <code>deckifyr serve --project &lt;directory&gt;</code> pointed at an
              existing project directory (one containing <code>presentation.yaml</code>).
            </li>
          </ul>
        </>
      )}
      <p className="no-project__hint">Reload this page once the project is in place.</p>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState<Tab>("editor");
  const { status: projectStatus, frontendWarning } = useProjectStatus();

  if (projectStatus.state === "checking") {
    return <div className="no-project no-project--checking">Loading&hellip;</div>;
  }
  if (projectStatus.state === "error") {
    return <NoProjectScreen message={projectStatus.message} launcher={projectStatus.launcher} />;
  }

  return (
    <AppProvider>
      <div className="app">
        {frontendWarning && (
          <div className="app__frontend-warning" role="alert">
            {frontendWarning}
          </div>
        )}
        <header className="app__header">
          <img src="/logo.png" alt="" className="app__logo" />
          <h1>deckifyr</h1>
          <span className="app__project-path" title={projectStatus.root}>
            {projectStatus.root}
          </span>
          <SessionControls />
          <nav className="app__tabs">
            <button className={tab === "editor" ? "active" : ""} onClick={() => setTab("editor")}>
              Editor
            </button>
            <button className={tab === "config" ? "active" : ""} onClick={() => setTab("config")}>
              Config
            </button>
            <button className={tab === "build" ? "active" : ""} onClick={() => setTab("build")}>
              Build
            </button>
          </nav>
        </header>
        <main className="app__main">
          {tab === "editor" && <EditorTab />}
          {tab === "config" && <ConfigEditor />}
          {tab === "build" && <BuildPanel />}
        </main>
      </div>
    </AppProvider>
  );
}
