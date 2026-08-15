import { useState } from "react";
import { AppProvider } from "./state/AppContext";
import { usePlan } from "./state/usePlan";
import SlideCanvas from "./components/SlideCanvas";
import SlideList from "./components/SlideList";
import ElementInspector from "./components/ElementInspector";
import Toolbar from "./components/Toolbar";
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
  return (
    <div className="editor-layout">
      <Toolbar plan={plan} />
      <div className="editor-layout__body">
        <SlideList plan={plan} />
        <SlideCanvas plan={plan} />
        <ElementInspector plan={plan} />
      </div>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState<Tab>("editor");

  return (
    <AppProvider>
      <div className="app">
        <header className="app__header">
          <h1>deckifyr</h1>
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
