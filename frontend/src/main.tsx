import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";
import "./styles/tailwind.css";

const queryClient = new QueryClient();

function renderApp(): void {
  ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
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
