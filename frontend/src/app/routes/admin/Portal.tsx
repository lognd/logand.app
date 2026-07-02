import { Link } from "react-router-dom";
import { LINK_CLASS } from "../../../styles/a11y";

// Single landing page for admins -- "make a portal for me to do everything
// from" -- linking the three real admin areas (invoicing, budget,
// inventory) that otherwise only invoicing was reachable from the top nav
// for. Deliberately no data-fetching/summary tiles here: each linked page
// already owns its own list/loading/error states, so duplicating live
// counts here would just be a second place for those numbers to drift out
// of sync with the real page.
export function AdminPortal() {
  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Admin portal</h1>
      <ul className="flex flex-col gap-4">
        <li>
          <Link to="/admin/invoices" className={LINK_CLASS}>
            Invoicing
          </Link>
          <p className="text-base text-fg-muted">
            Create invoices, send them, record payments, and download PDFs.
          </p>
        </li>
        <li>
          <Link to="/admin/budget" className={LINK_CLASS}>
            Budget
          </Link>
          <p className="text-base text-fg-muted">Track income and expenses.</p>
        </li>
        <li>
          <Link to="/admin/inventory" className={LINK_CLASS}>
            Inventory
          </Link>
          <p className="text-base text-fg-muted">Manage stocked items and quantities.</p>
        </li>
      </ul>
    </main>
  );
}
