import { formatLogsForExport } from "../../lib/logging";

// Always available (not just after a crash -- see ErrorBoundary.tsx for
// that path), so a customer hitting something merely WRONG (not a hard
// crash) still has a one-click way to hand over exactly what their
// browser saw, per "I should be able to retrieve logs from frontend if
// customer site crashes (they get logs that they can send to me)."
// Fixed position, low-key styling -- present everywhere without
// competing with real page content.
function downloadLogs(): void {
  const blob = new Blob([formatLogsForExport()], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `logand-client-log-${Date.now()}.txt`;
  a.click();
  URL.revokeObjectURL(url);
}

export function ReportProblemButton() {
  return (
    <button
      type="button"
      onClick={downloadLogs}
      aria-label="download a log file to report a problem"
      className="glass-panel fixed bottom-4 right-4 z-40 min-h-11 rounded px-3 py-2 text-sm text-fg-muted hover:text-fg-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-orange"
    >
      Report a problem
    </button>
  );
}
