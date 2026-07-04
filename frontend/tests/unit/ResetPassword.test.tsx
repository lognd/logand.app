import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResetPassword } from "../../src/app/routes/public/ResetPassword";
import * as authApi from "../../src/api/auth";
import { ApiError } from "../../src/api/client";

function renderWithToken(token: string | null) {
  const queryClient = new QueryClient();
  const initialEntry = token ? `/reset-password?token=${token}` : "/reset-password";
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <ResetPassword />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ResetPassword", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a missing-token message and no form when the URL has no token", () => {
    renderWithToken(null);
    expect(screen.getByText(/missing its reset token/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("New password")).not.toBeInTheDocument();
  });

  it("calls confirmPasswordReset with the token from the URL and the entered password", async () => {
    const confirmSpy = vi
      .spyOn(authApi, "confirmPasswordReset")
      .mockResolvedValue({ status: "ok" });
    const user = userEvent.setup();
    renderWithToken("real-token-abc");

    await user.type(screen.getByLabelText("New password"), "brand-new-password-456");
    await user.click(screen.getByRole("button", { name: "Reset password" }));

    await waitFor(() => {
      expect(confirmSpy).toHaveBeenCalledWith(
        "real-token-abc",
        "brand-new-password-456",
      );
    });
    expect(await screen.findByText(/has been reset/i)).toBeInTheDocument();
  });

  it("shows the backend's real detail message on an invalid or expired token", async () => {
    vi.spyOn(authApi, "confirmPasswordReset").mockRejectedValue(
      new ApiError(
        "password reset link is invalid or has expired",
        "AuthError.PasswordResetTokenInvalid",
      ),
    );
    const user = userEvent.setup();
    renderWithToken("stale-token");

    await user.type(screen.getByLabelText("New password"), "brand-new-password-456");
    await user.click(screen.getByRole("button", { name: "Reset password" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "password reset link is invalid or has expired",
    );
  });
});
