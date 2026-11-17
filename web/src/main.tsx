import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { installGuidance } from "./guidance";

const container = document.getElementById("root");
if (!container) {
  throw new Error("missing #root element");
}

installGuidance();

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>
);
