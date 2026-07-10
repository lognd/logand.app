import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Claim } from "../../src/app/routes/public/Claim";
import * as authApi from "../../src/api/auth";
import { ApiError } from "../../src/api/client";

function renderWithToken(token: string | null) {
  const queryClient = new QueryClient();
  const initialEntry = token ? `/claim?token=${token}` : "/claim";
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/claim" element={<Claim />} />
          <Route path="/login" element={<div>login page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Claim", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a missing-token message and no preview when the URL has no token", () => {
    renderWithToken(null);
    expect(screen.getByText(/missing its claim token/i)).toBeInTheDocument();
  });

  it("renders the invoice preview and lets the visitor set a password", async () => {
    vi.spyOn(authApi, "getClaimPreview").mockResolvedValue({
      email: "real-customer@example.com",
      invoices: [
        {
          id: "inv-1",
          status: "sent",
          amount_total: "10.00",
          currency: "usd",
          due_date: "2026-08-01",
        },
      ],
    });
    const confirmSpy = vi.spyOn(authApi, "confirmClaim").mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderWithToken("real-claim-token");

    expect(
      await screen.findByText("real-customer@example.com"),
    ).toBeInTheDocument();
    expect(screen.getByText(/10.00 USD/)).toBeInTheDocument();
    expect(screen.getByText(/Status: sent/)).toBeInTheDocument();

    await user.type(screen.getByLabelText("Password"), "claimed-password-123");
    await user.click(screen.getByRole("button", { name: "Set password" }));

    await waitFor(() => {
      expect(confirmSpy).toHaveBeenCalledWith(
        "real-claim-token",
        "claimed-password-123",
      );
    });
    expect(await screen.findByText("login page")).toBeInTheDocument();
  });

  it("shows the backend's real detail message on an invalid or expired token", async () => {
    vi.spyOn(authApi, "getClaimPreview").mockRejectedValue(
      new ApiError(
        "verification link is invalid, has expired, or was already used",
        "AuthError.EmailVerificationTokenInvalid",
      ),
    );
    renderWithToken("stale-claim-token");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "verification link is invalid, has expired, or was already used",
    );
  });
});
