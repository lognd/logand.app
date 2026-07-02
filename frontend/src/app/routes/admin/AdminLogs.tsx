import { useQuery } from "@tanstack/react-query";
import { listLogFiles, logFileDownloadUrl, tailLiveLog } from "../../../api/adminLogs";
import { BUTTON_CLASS } from "../../../styles/a11y";

// "I can retrieve logs from backend" -- browse real rotated log files and
// tail the live one without shelling into the VPS. Read-only: pruning is
// entirely handled server-side (logging/retention.py), never triggered
// from here.
export function AdminLogs() {
  const filesQuery = useQuery({
    queryKey: ["admin", "logs", "files"],
    queryFn: () => listLogFiles(),
  });
  const tailQuery = useQuery({
    queryKey: ["admin", "logs", "tail"],
    queryFn: () => tailLiveLog(200),
    refetchInterval: 10_000,
  });

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Server logs (admin)</h1>

      <section className="mb-8">
        <h2 className="mb-2 text-lg text-fg-primary">Log files</h2>
        {filesQuery.isLoading && <p className="text-fg-muted">Loading...</p>}
        {filesQuery.isError && (
          <p role="alert" className="text-accent-red">
            Failed to load log files.
          </p>
        )}
        <div className="flex flex-col gap-2">
          {filesQuery.data?.map((file) => (
            <div
              key={file.name}
              className="flex items-center justify-between rounded border border-border p-2 text-sm"
            >
              <span>
                {file.name} ({Math.round(file.size_bytes / 1024)} KB,{" "}
                {new Date(file.modified_at * 1000).toLocaleString()})
              </span>
              <a href={logFileDownloadUrl(file.name)} className={BUTTON_CLASS} download>
                Download
              </a>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-lg text-fg-primary">Live tail (last 200 lines)</h2>
        {tailQuery.isLoading && <p className="text-fg-muted">Loading...</p>}
        {tailQuery.isError && (
          <p role="alert" className="text-accent-red">
            Failed to load the live log.
          </p>
        )}
        <pre className="max-h-96 overflow-auto rounded border border-border bg-bg-primary p-3 text-xs text-fg-muted">
          {tailQuery.data?.join("\n")}
        </pre>
      </section>
    </main>
  );
}
