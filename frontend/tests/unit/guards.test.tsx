import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AdminGuard } from "../../src/app/layout/AdminGuard";
import { CustomerGuard } from "../../src/app/layout/CustomerGuard";
import * as authApi from "../../src/api/auth";
import { UnauthenticatedError } from "../../src/api/client";

function renderGuard(Guard: typeof AdminGuard, child = <p>protected content</p>) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/protected"]}>
        <Routes>
          <Route path="/login" element={<p>login page</p>} />
          <Route path="/protected" element={<Guard>{child}</Guard>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AdminGuard", () => {
  it("renders children once /api/me resolves with role=admin", async () => {
    vi.spyOn(authApi, "fetchMe").mockResolvedValue({
      user_id: "1",
      role: "admin",
    });
    renderGuard(AdminGuard);
    expect(await screen.findByText("protected content")).toBeInTheDocument();
  });

  it("renders Forbidden when the session role is customer, not admin", async () => {
    vi.spyOn(authApi, "fetchMe").mockResolvedValue({
      user_id: "1",
      role: "customer",
    });
    renderGuard(AdminGuard);
    expect(await screen.findByText("Forbidden.")).toBeInTheDocument();
  });

  it("redirects to /login when /api/me returns 401 (client.ts does not redirect on this GET)", async () => {
    // Regression test for FE1: client.ts deliberately exempts GET
    // /api/me from its own 401-redirect handling (see that module's own
    // comment), so the guard itself must be the thing that navigates a
    // logged-out/expired-session visitor away from a protected route
    // instead of leaving them on a blank page forever.
    vi.spyOn(authApi, "fetchMe").mockRejectedValue(new UnauthenticatedError());
    renderGuard(AdminGuard);
    expect(await screen.findByText("login page")).toBeInTheDocument();
  });

  it("shows a retry message (not a redirect) when /api/me fails for a non-auth reason", async () => {
    // Regression test for M3: a transient network/5xx failure on
    // /api/me is not "logged out" -- bouncing an already-authenticated
    // admin to /login on a blip is wrong, see the guard's own comment.
    vi.spyOn(authApi, "fetchMe").mockRejectedValue(new Error("network error"));
    renderGuard(AdminGuard);
    expect(
      await screen.findByText(/Something went wrong loading your account/),
    ).toBeInTheDocument();
  });
});

describe("CustomerGuard", () => {
  it("renders children once /api/me resolves with role=customer", async () => {
    vi.spyOn(authApi, "fetchMe").mockResolvedValue({
      user_id: "2",
      role: "customer",
    });
    renderGuard(CustomerGuard);
    expect(await screen.findByText("protected content")).toBeInTheDocument();
  });

  it("renders Forbidden when the session role is admin, not customer", async () => {
    vi.spyOn(authApi, "fetchMe").mockResolvedValue({
      user_id: "2",
      role: "admin",
    });
    renderGuard(CustomerGuard);
    expect(await screen.findByText("Forbidden.")).toBeInTheDocument();
  });

  it("redirects to /login when /api/me returns 401", async () => {
    vi.spyOn(authApi, "fetchMe").mockRejectedValue(new UnauthenticatedError());
    renderGuard(CustomerGuard);
    expect(await screen.findByText("login page")).toBeInTheDocument();
  });

  it("shows a retry message (not a redirect) when /api/me fails for a non-auth reason", async () => {
    vi.spyOn(authApi, "fetchMe").mockRejectedValue(new Error("network error"));
    renderGuard(CustomerGuard);
    expect(
      await screen.findByText(/Something went wrong loading your account/),
    ).toBeInTheDocument();
  });
});
