import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { VerifyEmail } from "../../src/app/routes/public/VerifyEmail";
import * as authApi from "../../src/api/auth";
import { ApiError } from "../../src/api/client";

function renderWithToken(token: string | null) {
  const queryClient = new QueryClient();
  const initialEntry = token ? `/verify-email?token=${token}` : "/verify-email";
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/verify-email" element={<VerifyEmail />} />
          <Route path="/login" element={<div>login page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("VerifyEmail", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a missing-token message and the resend form when the URL has no token", () => {
    renderWithToken(null);
    expect(screen.getByText(/missing its verification token/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
  });

  it("lets the visitor choose a password and POSTs {token, password}, then goes to login (FINDINGS H1)", async () => {
    const verifySpy = vi.spyOn(authApi, "verifyEmail").mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderWithToken("real-token-abc");

    await user.type(screen.getByLabelText("Password"), "chosen-at-verify-time");
    await user.click(
      screen.getByRole("button", { name: "Verify and set password" }),
    );

    await waitFor(() => {
      expect(verifySpy).toHaveBeenCalledWith(
        "real-token-abc",
        "chosen-at-verify-time",
      );
    });
    expect(await screen.findByText("login page")).toBeInTheDocument();
  });

  it("shows the backend's real detail message and a resend affordance on an invalid or expired token", async () => {
    vi.spyOn(authApi, "verifyEmail").mockRejectedValue(
      new ApiError(
        "verification link is invalid, has expired, or was already used",
        "AuthError.EmailVerificationTokenInvalid",
      ),
    );
    const user = userEvent.setup();
    renderWithToken("stale-token");

    await user.type(screen.getByLabelText("Password"), "chosen-at-verify-time");
    await user.click(
      screen.getByRole("button", { name: "Verify and set password" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "verification link is invalid, has expired, or was already used",
    );
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
  });

  it("shows the same generic confirmation from the resend form regardless of account existence", async () => {
    vi.spyOn(authApi, "resendVerification").mockResolvedValue({ status: "ok" });
    const user = userEvent.setup();
    renderWithToken(null);

    await user.type(screen.getByLabelText("Email"), "nobody@example.com");
    await user.click(
      screen.getByRole("button", { name: "Resend verification email" }),
    );

    expect(
      await screen.findByText(/if a pending registration exists for that email/i),
    ).toBeInTheDocument();
  });
});
