import { useEffect, useState } from "react";
import { AppProvider, useAppContext } from "./state/AppContext";
import { usePlan } from "./state/usePlan";
import { ApiError, getHealth, getProject } from "./api/client";
import type { Launcher } from "./types";
import SlideCanvas from "./components/SlideCanvas";
import SlideList from "./components/SlideList";
import ElementInspector from "./components/ElementInspector";
import Toolbar from "./components/Toolbar";
import DeckOptions from "./components/DeckOptions";
import FurnitureControls from "./components/FurnitureControls";
import ConfigEditor from "./components/ConfigEditor";
import BuildPanel from "./components/BuildPanel";
import "./App.css";

type Tab = "editor" | "config" | "build";

function EditorTab() {
  // `usePlan` is called once here (not inside SlideCanvas itself) so
  // SlideList/Toolbar/ElementInspector all see the same fetched slide
  // list and share one set of undo/redo history bookkeeping instead of
  // each firing its own `/api/plan` request -- see `state/usePlan.ts`'s
  // own module docstring for the fuller rationale.
  const plan = usePlan();
  const { state } = useAppContext();
  const isFurnitureSlideSelected =
    plan.furnitureSlide !== null && state.selectedSlideId === plan.furnitureSlide.id;
  return (
    <div className="editor-layout">
      <Toolbar plan={plan} />
      <DeckOptions onSaved={plan.refetch} />
      {isFurnitureSlideSelected && <FurnitureControls plan={plan} />}
      <div className="editor-layout__body">
        <SlideList plan={plan} />
        <SlideCanvas plan={plan} />
        <ElementInspector plan={plan} />
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
function useProjectStatus(): ProjectStatus {
  const [status, setStatus] = useState<ProjectStatus>({ state: "checking" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      let launcher: Launcher | null = null;
      try {
        launcher = (await getHealth()).launcher;
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

  return status;
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
  const projectStatus = useProjectStatus();

  if (projectStatus.state === "checking") {
    return <div className="no-project no-project--checking">Loading&hellip;</div>;
  }
  if (projectStatus.state === "error") {
    return <NoProjectScreen message={projectStatus.message} launcher={projectStatus.launcher} />;
  }

  return (
    <AppProvider>
      <div className="app">
        <header className="app__header">
          <img src="/logo.png" alt="" className="app__logo" />
          <h1>deckifyr</h1>
          <span className="app__project-path" title={projectStatus.root}>
            {projectStatus.root}
          </span>
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
