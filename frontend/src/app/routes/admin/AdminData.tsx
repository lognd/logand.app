import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteRow,
  getRow,
  getTableSchema,
  listChanges,
  listRows,
  listTables,
  revertChange,
  updateRow,
} from "../../../api/adminData";
import { BUTTON_CLASS, INPUT_CLASS, LABEL_CLASS } from "../../../styles/a11y";

// The "absolute power, but never a corrupt state" admin data browser --
// generic over every real table (api/admin_data.py), never a hardcoded
// per-table form. Every write requires the same explicit confirm step,
// showing the EXACT before-to-after diff, not a generic "are you sure",
// as every other risky admin action on this site.

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "(null)";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function RowEditor({
  tableName,
  rowId,
  onClose,
}: {
  tableName: string;
  rowId: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [confirming, setConfirming] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const schemaQuery = useQuery({
    queryKey: ["admin", "data", "schema", tableName],
    queryFn: () => getTableSchema(tableName),
  });
  const rowQuery = useQuery({
    queryKey: ["admin", "data", "row", tableName, rowId],
    queryFn: () => getRow(tableName, rowId),
  });

  const invalidateList = () =>
    queryClient.invalidateQueries({ queryKey: ["admin", "data", "rows", tableName] });

  const updateMutation = useMutation({
    mutationFn: () => updateRow(tableName, rowId, edits),
    onSuccess: () => {
      setConfirming(false);
      setEdits({});
      invalidateList();
      queryClient.invalidateQueries({
        queryKey: ["admin", "data", "row", tableName, rowId],
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteRow(tableName, rowId),
    onSuccess: () => {
      invalidateList();
      onClose();
    },
  });

  if (schemaQuery.isLoading || rowQuery.isLoading) {
    return <p className="text-fg-muted">Loading...</p>;
  }
  if (schemaQuery.isError || rowQuery.isError || !schemaQuery.data || !rowQuery.data) {
    return (
      <p role="alert" className="text-accent-red">
        Could not load this row.
      </p>
    );
  }

  const row = rowQuery.data;
  const changedKeys = Object.keys(edits).filter((k) => edits[k] !== String(row[k] ?? ""));

  return (
    <div className="rounded border border-border p-3">
      <div className="flex items-center justify-between">
        <p className="text-base text-fg-primary">
          {tableName} / {rowId}
        </p>
        <button type="button" onClick={onClose} className={BUTTON_CLASS}>
          Close
        </button>
      </div>

      <div className="mt-3 flex flex-col gap-2">
        {schemaQuery.data.map((col) => (
          <div key={col.name}>
            <label htmlFor={`field-${col.name}`} className={LABEL_CLASS}>
              {col.name}
              {!col.editable && " (read-only)"}
            </label>
            <input
              id={`field-${col.name}`}
              type="text"
              disabled={!col.editable}
              value={edits[col.name] ?? formatValue(row[col.name])}
              onChange={(e) =>
                setEdits((prev) => ({ ...prev, [col.name]: e.target.value }))
              }
              className={INPUT_CLASS}
            />
          </div>
        ))}
      </div>

      {!confirming ? (
        <button
          type="button"
          disabled={changedKeys.length === 0}
          onClick={() => setConfirming(true)}
          className={`${BUTTON_CLASS} mt-3`}
        >
          Review changes
        </button>
      ) : (
        <div className="mt-3 rounded border border-border p-3">
          <p className="text-base text-fg-primary">
            Confirm the following change{changedKeys.length > 1 ? "s" : ""}:
          </p>
          <ul className="mt-2 flex flex-col gap-1 text-sm">
            {changedKeys.map((key) => (
              <li key={key}>
                <span className="text-fg-muted">{key}:</span>{" "}
                <span className="text-accent-red">{formatValue(row[key])}</span>
                {" -> "}
                <span className="text-accent-green">{edits[key]}</span>
              </li>
            ))}
          </ul>
          {updateMutation.isError && (
            <p role="alert" className="mt-2 text-sm text-accent-red">
              Could not apply this change -- it may violate a database constraint.
            </p>
          )}
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              disabled={updateMutation.isPending}
              onClick={() => updateMutation.mutate()}
              className={BUTTON_CLASS}
            >
              Confirm change
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className={BUTTON_CLASS}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {!confirmingDelete ? (
        <button
          type="button"
          onClick={() => setConfirmingDelete(true)}
          className={`${BUTTON_CLASS} mt-3`}
        >
          Delete row
        </button>
      ) : (
        <div className="mt-3 rounded border border-border p-3">
          <p className="text-base text-fg-primary">
            This will permanently delete this row from <strong>{tableName}</strong>. It
            can be restored afterward from the change log below.
          </p>
          {deleteMutation.isError && (
            <p role="alert" className="mt-2 text-sm text-accent-red">
              Could not delete this row -- another table may still reference it.
            </p>
          )}
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              disabled={deleteMutation.isPending}
              onClick={() => deleteMutation.mutate()}
              className={BUTTON_CLASS}
            >
              Confirm delete
            </button>
            <button
              type="button"
              onClick={() => setConfirmingDelete(false)}
              className={BUTTON_CLASS}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function ChangeLog() {
  const queryClient = useQueryClient();
  const [confirmingRevertId, setConfirmingRevertId] = useState<string | null>(null);

  const changesQuery = useQuery({
    queryKey: ["admin", "data", "changes"],
    queryFn: () => listChanges(),
  });

  const revertMutation = useMutation({
    mutationFn: (changeId: string) => revertChange(changeId),
    onSuccess: () => {
      setConfirmingRevertId(null);
      queryClient.invalidateQueries({ queryKey: ["admin", "data"] });
    },
  });

  if (changesQuery.isLoading) return <p className="text-fg-muted">Loading...</p>;
  if (changesQuery.isError || !changesQuery.data) {
    return (
      <p role="alert" className="text-accent-red">
        Could not load the change log.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {changesQuery.data.length === 0 && (
        <p className="text-fg-muted">No changes recorded yet.</p>
      )}
      {changesQuery.data.map((entry) => (
        <div key={entry.id} className="rounded border border-border p-3 text-sm">
          <p>
            <span className="text-fg-muted">{new Date(entry.created_at).toLocaleString()}</span>
            {" -- "}
            <span className="text-fg-primary">{entry.action}</span>
            {entry.target_table && (
              <span className="text-fg-muted">
                {" "}
                on {entry.target_table}/{entry.target_id}
              </span>
            )}
          </p>
          {entry.before_state && (
            <p className="text-accent-red">before: {JSON.stringify(entry.before_state)}</p>
          )}
          {entry.after_state && (
            <p className="text-accent-green">after: {JSON.stringify(entry.after_state)}</p>
          )}

          {confirmingRevertId === entry.id ? (
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                disabled={revertMutation.isPending}
                onClick={() => revertMutation.mutate(entry.id)}
                className={BUTTON_CLASS}
              >
                Confirm revert
              </button>
              <button
                type="button"
                onClick={() => setConfirmingRevertId(null)}
                className={BUTTON_CLASS}
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmingRevertId(entry.id)}
              className={`${BUTTON_CLASS} mt-2`}
            >
              Revert this change
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

export function AdminData() {
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [selectedRowId, setSelectedRowId] = useState<string | null>(null);
  const [showChangeLog, setShowChangeLog] = useState(false);

  const tablesQuery = useQuery({
    queryKey: ["admin", "data", "tables"],
    queryFn: () => listTables(),
  });

  const rowsQuery = useQuery({
    queryKey: ["admin", "data", "rows", selectedTable],
    queryFn: () => listRows(selectedTable as string),
    enabled: !!selectedTable,
  });

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8">
      <h1 className="mb-2 text-2xl text-fg-primary">Data browser (admin)</h1>
      <p className="mb-6 text-sm text-fg-muted">
        Direct table access for one-off fixes. Every write is validated against the
        real database constraints and recorded in the change log below, so it can
        always be reverted.
      </p>

      <button
        type="button"
        onClick={() => setShowChangeLog((v) => !v)}
        className={`${BUTTON_CLASS} mb-6`}
      >
        {showChangeLog ? "Hide change log" : "Show change log"}
      </button>
      {showChangeLog && (
        <div className="mb-6">
          <ChangeLog />
        </div>
      )}

      <div className="mb-4">
        <label htmlFor="table-select" className={LABEL_CLASS}>
          Table
        </label>
        <select
          id="table-select"
          value={selectedTable ?? ""}
          onChange={(e) => {
            setSelectedTable(e.target.value || null);
            setSelectedRowId(null);
          }}
          className={INPUT_CLASS}
        >
          <option value="">Select a table...</option>
          {tablesQuery.data?.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </div>

      {rowsQuery.isLoading && <p className="text-fg-muted">Loading rows...</p>}
      {rowsQuery.isError && (
        <p role="alert" className="text-accent-red">
          Failed to load rows.
        </p>
      )}

      {rowsQuery.data && (
        <div className="flex flex-col gap-2">
          {rowsQuery.data.map((row) => {
            const rowId = String(row.id);
            return (
              <div key={rowId}>
                <button
                  type="button"
                  onClick={() =>
                    setSelectedRowId(selectedRowId === rowId ? null : rowId)
                  }
                  className={`${BUTTON_CLASS} w-full text-left`}
                >
                  {rowId}
                </button>
                {selectedRowId === rowId && selectedTable && (
                  <div className="mt-2">
                    <RowEditor
                      tableName={selectedTable}
                      rowId={rowId}
                      onClose={() => setSelectedRowId(null)}
                    />
                  </div>
                )}
              </div>
            );
          })}
          {rowsQuery.data.length === 0 && (
            <p className="text-fg-muted">No rows in this table.</p>
          )}
        </div>
      )}
    </main>
  );
}
