import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deactivateCustomer,
  getCustomerDetail,
  listCustomers,
  reactivateCustomer,
  resetCustomerPassword,
} from "../../../api/customers";
import { BUTTON_CLASS, INPUT_CLASS, LABEL_CLASS } from "../../../styles/a11y";

// Every write here (deactivate/reactivate/reset password) is a real
// account-affecting, hard-to-casually-undo action -- same site-wide
// "confirmations on everything" requirement as inventory's /adjust
// route, so each one gets its own explicit confirm step showing exactly
// what's about to happen before the request fires.
function CustomerDetailPanel({ userId }: { userId: string }) {
  const queryClient = useQueryClient();
  const [confirmingDeactivate, setConfirmingDeactivate] = useState(false);
  const [resettingPassword, setResettingPassword] = useState(false);
  const [newPassword, setNewPassword] = useState("");

  const detailQuery = useQuery({
    queryKey: ["admin", "customers", userId],
    queryFn: () => getCustomerDetail(userId),
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["admin", "customers", userId] });

  const deactivateMutation = useMutation({
    mutationFn: () => deactivateCustomer(userId),
    onSuccess: () => {
      setConfirmingDeactivate(false);
      invalidate();
    },
  });

  const reactivateMutation = useMutation({
    mutationFn: () => reactivateCustomer(userId),
    onSuccess: invalidate,
  });

  const resetPasswordMutation = useMutation({
    mutationFn: () => resetCustomerPassword(userId, newPassword),
    onSuccess: () => {
      setResettingPassword(false);
      setNewPassword("");
    },
  });

  if (detailQuery.isLoading) return <p className="text-fg-muted">Loading...</p>;
  if (detailQuery.isError || !detailQuery.data) {
    return (
      <p role="alert" className="text-accent-red">
        Could not load this customer.
      </p>
    );
  }

  const customer = detailQuery.data;

  return (
    <div className="rounded border border-border p-4">
      <p className="text-lg text-fg-primary">{customer.email}</p>
      <p className="text-sm text-fg-muted">
        Account created {new Date(customer.created_at).toLocaleDateString()}
      </p>
      <p className="mt-1 text-sm">
        Status:{" "}
        {customer.disabled_at ? (
          <span className="text-accent-red">
            Deactivated ({new Date(customer.disabled_at).toLocaleString()})
          </span>
        ) : (
          <span className="text-accent-green">Active</span>
        )}
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        {customer.disabled_at ? (
          <button
            type="button"
            disabled={reactivateMutation.isPending}
            onClick={() => reactivateMutation.mutate()}
            className={BUTTON_CLASS}
          >
            Reactivate account
          </button>
        ) : !confirmingDeactivate ? (
          <button
            type="button"
            onClick={() => setConfirmingDeactivate(true)}
            className={BUTTON_CLASS}
          >
            Deactivate account
          </button>
        ) : (
          <div className="w-full rounded border border-border p-3">
            <p className="text-base text-fg-primary">
              This will immediately prevent <strong>{customer.email}</strong> from
              logging in. Their data/invoices are untouched -- reactivate to
              restore login access at any time.
            </p>
            {deactivateMutation.isError && (
              <p role="alert" className="mt-2 text-base text-accent-red">
                Could not deactivate this account.
              </p>
            )}
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                disabled={deactivateMutation.isPending}
                onClick={() => deactivateMutation.mutate()}
                className={BUTTON_CLASS}
              >
                Confirm deactivate
              </button>
              <button
                type="button"
                onClick={() => setConfirmingDeactivate(false)}
                className={BUTTON_CLASS}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {!resettingPassword ? (
          <button
            type="button"
            onClick={() => setResettingPassword(true)}
            className={BUTTON_CLASS}
          >
            Reset password
          </button>
        ) : (
          <div className="w-full rounded border border-border p-3">
            <label htmlFor="new-password" className={LABEL_CLASS}>
              New password for {customer.email}
            </label>
            <input
              id="new-password"
              type="text"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className={INPUT_CLASS}
            />
            {resetPasswordMutation.isError && (
              <p role="alert" className="mt-2 text-base text-accent-red">
                Could not reset the password -- must be at least 8 characters.
              </p>
            )}
            {resetPasswordMutation.isSuccess && (
              <p className="mt-2 text-base text-fg-primary">
                Password reset. Share the new password with the customer securely.
              </p>
            )}
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                disabled={newPassword.length < 8 || resetPasswordMutation.isPending}
                onClick={() => resetPasswordMutation.mutate()}
                className={BUTTON_CLASS}
              >
                Confirm reset
              </button>
              <button
                type="button"
                onClick={() => {
                  setResettingPassword(false);
                  setNewPassword("");
                }}
                className={BUTTON_CLASS}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function AdminCustomers() {
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const customersQuery = useQuery({
    queryKey: ["admin", "customers", "search", query],
    queryFn: () => listCustomers(query || undefined),
  });

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Customer accounts (admin)</h1>

      <div className="mb-6">
        <label htmlFor="customer-search" className={LABEL_CLASS}>
          Search customers
        </label>
        <input
          id="customer-search"
          type="text"
          placeholder="Search by email..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className={INPUT_CLASS}
        />
      </div>

      {customersQuery.isLoading && <p className="text-fg-muted">Loading...</p>}
      {customersQuery.isError && (
        <p role="alert" className="text-accent-red">
          Failed to load customers.
        </p>
      )}
      <div className="flex flex-col gap-2">
        {customersQuery.data?.map((customer) => (
          <div key={customer.id}>
            <button
              type="button"
              onClick={() =>
                setSelectedId(selectedId === customer.id ? null : customer.id)
              }
              className={`${BUTTON_CLASS} w-full text-left`}
            >
              {customer.email}
            </button>
            {selectedId === customer.id && (
              <div className="mt-2">
                <CustomerDetailPanel userId={customer.id} />
              </div>
            )}
          </div>
        ))}
        {customersQuery.data?.length === 0 && (
          <p className="text-fg-muted">No customers match.</p>
        )}
      </div>
    </main>
  );
}
