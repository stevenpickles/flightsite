import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "@/App";
import "@/index.css";
import { registerServiceWorker } from "@/lib/pwa/registerServiceWorker";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// After the first render, and never awaited: the service worker (roadmap
// slice 084) is production-only and guarded, and registration resolves to
// `null` rather than throwing, so it can never hold up or break the app.
void registerServiceWorker();
