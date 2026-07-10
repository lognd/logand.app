import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deactivateCustomer,
  getCustomerDetail,
  listCustomers,
  reactivateCustomer,
  resetCustomerPassword,
  updateCustomerAddress,
  type AccountState,
  type CustomerDetail,
} from "../../../api/customers";
import { BUTTON_CLASS, INPUT_CLASS, LABEL_CLASS } from "../../../styles/a11y";

// Plain-language copy for docs/design/17's account states, aimed at a
// solo business owner chasing an unpaid invoice, not a database term --
// "did they ever even get in?" is the question this answers at a glance.
const ACCOUNT_STATE_COPY: Record<AccountState, string> = {
  contact: "No account yet -- invoice sent, not claimed",
  unverified: "Signed up, has not confirmed their email",
  active: "Active",
};

// Color only ever comes from tokens.css custom properties -- never a
// hardcoded hex -- so the badge follows the site's theme automatically.
const ACCOUNT_STATE_CLASS: Record<AccountState, string> = {
  contact: "text-fg-muted",
  unverified: "text-accent-orange",
  active: "text-accent-green",
};

function AccountStateBadge({ state }: { state: AccountState }) {
  return (
    <span className={`text-sm ${ACCOUNT_STATE_CLASS[state]}`}>
      {ACCOUNT_STATE_COPY[state]}
    </span>
  );
}

// Every write here (deactivate/reactivate/reset password) is a real
// account-affecting, hard-to-casually-undo action -- same site-wide
// "confirmations on everything" requirement as inventory's /adjust
// route, so each one gets its own explicit confirm step showing exactly
// what's about to happen before the request fires.
// Destination address used by the tax engine's jurisdiction lookup (see
// docs/design/16-sales-tax.md Phase 6) -- a plain always-visible form
// (unlike the confirm-gated deactivate/reset flows above) since editing an
// address is not a destructive action that needs a second confirm step.
function AddressForm({ customer }: { customer: CustomerDetail }) {
  const queryClient = useQueryClient();
  const [line1, setLine1] = useState(customer.address_line1 ?? "");
  const [city, setCity] = useState(customer.address_city ?? "");
  const [state, setState] = useState(customer.address_state ?? "");
  const [postalCode, setPostalCode] = useState(customer.address_postal_code ?? "");
  const [country, setCountry] = useState(customer.address_country ?? "");

  const saveMutation = useMutation({
    mutationFn: () =>
      updateCustomerAddress(customer.id, {
        address_line1: line1 || null,
        address_city: city || null,
        address_state: state || null,
        address_postal_code: postalCode || null,
        address_country: country || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "customers", customer.id] });
    },
  });

  return (
    <div className="mt-4 rounded border border-border p-4">
      <p className="text-base text-fg-primary">Address (for tax sourcing)</p>
      <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="flex flex-col text-sm text-fg-muted">
          Address line 1
          <input
            type="text"
            value={line1}
            onChange={(e) => setLine1(e.target.value)}
            className={INPUT_CLASS}
          />
        </label>
        <label className="flex flex-col text-sm text-fg-muted">
          City
          <input
            type="text"
            value={city}
            onChange={(e) => setCity(e.target.value)}
            className={INPUT_CLASS}
          />
        </label>
        <label className="flex flex-col text-sm text-fg-muted">
          State
          <input
            type="text"
            value={state}
            onChange={(e) => setState(e.target.value)}
            className={INPUT_CLASS}
          />
        </label>
        <label className="flex flex-col text-sm text-fg-muted">
          Postal code
          <input
            type="text"
            value={postalCode}
            onChange={(e) => setPostalCode(e.target.value)}
            className={INPUT_CLASS}
          />
        </label>
        <label className="flex flex-col text-sm text-fg-muted">
          Country
          <input
            type="text"
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            className={INPUT_CLASS}
          />
        </label>
      </div>
      {saveMutation.isError && (
        <p role="alert" className="mt-2 text-base text-accent-red">
          Could not save the address.
        </p>
      )}
      {saveMutation.isSuccess && (
        <p className="mt-2 text-base text-fg-primary">Address saved.</p>
      )}
      <div className="mt-3">
        <button
          type="button"
          disabled={saveMutation.isPending}
          onClick={() => saveMutation.mutate()}
          className={BUTTON_CLASS}
        >
          Save address
        </button>
      </div>
    </div>
  );
}

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
      <p className="mt-1">
        <AccountStateBadge state={customer.account_state} />
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

      <AddressForm customer={customer} />
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
              <span>{customer.email}</span>
              <span className="ml-2">
                <AccountStateBadge state={customer.account_state} />
              </span>
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
