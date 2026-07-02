import { Link } from "react-router-dom";
import { LINK_CLASS } from "../../../styles/a11y";

// Customer home base after login -- previously /invoices was the only
// customer-facing route, with no landing page to arrive at first.
export function CustomerPortal() {
  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Your account</h1>
      <ul className="flex flex-col gap-4">
        <li>
          <Link to="/invoices" className={LINK_CLASS}>
            Invoices
          </Link>
          <p className="text-base text-fg-muted">
            View your invoices, pay online, or download PDFs.
          </p>
        </li>
      </ul>
    </main>
  );
}
