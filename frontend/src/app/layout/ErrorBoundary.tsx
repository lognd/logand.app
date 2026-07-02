import { Component, type ErrorInfo, type ReactNode } from "react";
import { formatLogsForExport, logError } from "../../lib/logging";
import { BUTTON_CLASS } from "../../styles/a11y";

interface Props {
  children: ReactNode;
}

interface State {
  crashed: boolean;
}

function downloadLogs(): void {
  const blob = new Blob([formatLogsForExport()], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `logand-client-log-${Date.now()}.txt`;
  a.click();
  URL.revokeObjectURL(url);
}

// Top-level render-crash catcher -- React error boundaries can only catch
// render-phase errors (not event handlers or async code; those go through
// lib/logging.ts's window.onerror/unhandledrejection listeners instead),
// but a render crash is exactly the case where the rest of the app is
// otherwise a blank white screen with no way to even ask the user what
// happened. Wrapping <App/> here means there's always still a page: a
// friendly message plus a real, working "download logs" button, so a
// customer can send the developer something concrete instead of just
// "the site broke."
export class ErrorBoundary extends Component<Props, State> {
  state: State = { crashed: false };

  static getDerivedStateFromError(): State {
    return { crashed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    logError("React render crash", `${error.stack ?? error.message}\n${info.componentStack}`);
  }

  render() {
    if (!this.state.crashed) return this.props.children;
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-2xl flex-col items-center justify-center px-4 text-center">
        <h1 className="text-2xl text-fg-primary">Something went wrong</h1>
        <p className="mt-2 text-base text-fg-muted">
          This page crashed unexpectedly. Downloading a log file and sending it
          along helps track down exactly what happened.
        </p>
        <div className="mt-4 flex gap-2">
          <button type="button" onClick={downloadLogs} className={BUTTON_CLASS}>
            Download logs
          </button>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className={BUTTON_CLASS}
          >
            Reload page
          </button>
        </div>
      </main>
    );
  }
}
