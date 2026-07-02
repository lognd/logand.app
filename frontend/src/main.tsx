import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";
import { ErrorBoundary } from "./app/layout/ErrorBoundary";
import { installGlobalLogging } from "./lib/logging";
import "./styles/tailwind.css";

// Installed before anything else renders -- window.onerror/
// unhandledrejection need to be listening from the very first tick, or
// an early crash (e.g. during the very first render) would be missed
// entirely. See lib/logging.ts.
installGlobalLogging();

const queryClient = new QueryClient();

function renderApp(): void {
  ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
    <React.StrictMode>
      <ErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </QueryClientProvider>
      </ErrorBoundary>
    </React.StrictMode>,
  );
}

// Dynamic import so MSW's code never ships in a normal production build --
// only loaded when VITE_USE_MOCKS=true (see frontend/.env.example and the
// "dev:mock" npm script). Lets the frontend run as a standalone mockup
// against a fake API, no real backend required -- see src/mocks/handlers.ts.
if (import.meta.env.VITE_USE_MOCKS === "true") {
  import("./mocks/browser").then(({ worker }) => {
    worker.start({ onUnhandledRequest: "bypass" }).then(renderApp);
  });
} else {
  renderApp();
}
