import { useQuery } from "@tanstack/react-query";
import { getVersionInfo } from "../../../api/adminVersion";

// "What version of everything do I have on the server" -- app version,
// deployed git commit, Python version, and every installed dependency's
// version, all read live from the running process (see
// api/admin_version.py) rather than trusted from a stale doc.
export function AdminVersion() {
  const versionQuery = useQuery({
    queryKey: ["admin", "version"],
    queryFn: () => getVersionInfo(),
  });

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Server version (admin)</h1>

      {versionQuery.isLoading && <p className="text-fg-muted">Loading...</p>}
      {versionQuery.isError && (
        <p role="alert" className="text-accent-red">
          Failed to load version info.
        </p>
      )}

      {versionQuery.data && (
        <>
          <dl className="mb-8 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-fg-muted">App version</dt>
            <dd className="text-fg-primary">{versionQuery.data.app_version}</dd>
            <dt className="text-fg-muted">Git commit</dt>
            <dd className="text-fg-primary">{versionQuery.data.git_commit}</dd>
            <dt className="text-fg-muted">Python version</dt>
            <dd className="text-fg-primary">{versionQuery.data.python_version}</dd>
            <dt className="text-fg-muted">Platform</dt>
            <dd className="text-fg-primary">{versionQuery.data.platform}</dd>
          </dl>

          <h2 className="mb-2 text-lg text-fg-primary">
            Dependencies ({Object.keys(versionQuery.data.dependencies).length})
          </h2>
          <div className="max-h-96 overflow-auto rounded border border-border">
            <table className="w-full text-sm">
              <tbody>
                {Object.entries(versionQuery.data.dependencies).map(([name, ver]) => (
                  <tr key={name} className="border-b border-border last:border-0">
                    <td className="p-2 text-fg-primary">{name}</td>
                    <td className="p-2 text-fg-muted">{ver}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </main>
  );
}
