import { Routes, Route } from "react-router-dom";
import { Shell } from "./app/layout/Shell";
import { AdminGuard } from "./app/layout/AdminGuard";
import { CustomerGuard } from "./app/layout/CustomerGuard";
import { Landing } from "./app/routes/public/Landing";
import { Projects } from "./app/routes/public/Projects";
import { Contact } from "./app/routes/public/Contact";
import { Login } from "./app/routes/public/Login";
import { AdminInvoices } from "./app/routes/admin/Invoices";
import { AdminBudget } from "./app/routes/admin/Budget";
import { AdminInventory } from "./app/routes/admin/Inventory";
import { CustomerInvoices } from "./app/routes/customer/Invoices";
import { CustomerPay } from "./app/routes/customer/Pay";

export function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/projects" element={<Projects />} />
        <Route path="/contact" element={<Contact />} />
        <Route path="/login" element={<Login />} />

        <Route
          path="/admin/invoices"
          element={
            <AdminGuard>
              <AdminInvoices />
            </AdminGuard>
          }
        />
        <Route
          path="/admin/budget"
          element={
            <AdminGuard>
              <AdminBudget />
            </AdminGuard>
          }
        />
        <Route
          path="/admin/inventory"
          element={
            <AdminGuard>
              <AdminInventory />
            </AdminGuard>
          }
        />

        <Route
          path="/invoices"
          element={
            <CustomerGuard>
              <CustomerInvoices />
            </CustomerGuard>
          }
        />
        <Route
          path="/invoices/:id/pay"
          element={
            <CustomerGuard>
              <CustomerPay />
            </CustomerGuard>
          }
        />
      </Routes>
    </Shell>
  );
}
