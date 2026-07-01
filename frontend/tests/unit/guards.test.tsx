import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { AdminGuard } from "../../src/app/layout/AdminGuard";
import { CustomerGuard } from "../../src/app/layout/CustomerGuard";
import * as authApi from "../../src/api/auth";

function renderGuard(Guard: typeof AdminGuard, child = <p>protected content</p>) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <Guard>{child}</Guard>
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

  it("renders nothing (client.ts already redirected) when /api/me errors", async () => {
    vi.spyOn(authApi, "fetchMe").mockRejectedValue(new Error("unauthenticated"));
    const { container } = renderGuard(AdminGuard);
    await waitFor(() => {
      expect(container.textContent).toBe("");
    });
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
});
