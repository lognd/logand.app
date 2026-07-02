import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AdminPortal } from "../../src/app/routes/admin/Portal";
import { CustomerPortal } from "../../src/app/routes/customer/Portal";

describe("AdminPortal", () => {
  it("links to invoicing, budget, and inventory", () => {
    render(
      <MemoryRouter>
        <AdminPortal />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Invoicing" })).toHaveAttribute(
      "href",
      "/admin/invoices",
    );
    expect(screen.getByRole("link", { name: "Budget" })).toHaveAttribute(
      "href",
      "/admin/budget",
    );
    expect(screen.getByRole("link", { name: "Inventory" })).toHaveAttribute(
      "href",
      "/admin/inventory",
    );
  });
});

describe("CustomerPortal", () => {
  it("links to invoices", () => {
    render(
      <MemoryRouter>
        <CustomerPortal />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Invoices" })).toHaveAttribute(
      "href",
      "/invoices",
    );
  });
});
