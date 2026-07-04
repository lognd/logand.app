import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ForgotPassword } from "../../src/app/routes/public/ForgotPassword";
import * as authApi from "../../src/api/auth";
import { RateLimitedError } from "../../src/api/client";

function renderWithClient() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ForgotPassword />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ForgotPassword", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls requestPasswordReset with the entered email on submit", async () => {
    const requestSpy = vi
      .spyOn(authApi, "requestPasswordReset")
      .mockResolvedValue({ status: "ok" });
    const user = userEvent.setup();
    renderWithClient();

    await user.type(screen.getByLabelText("Email"), "logan@logandapp.com");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));

    await waitFor(() => {
      expect(requestSpy).toHaveBeenCalledWith("logan@logandapp.com");
    });
  });

  it("shows the same generic success message regardless of whether the account exists", async () => {
    vi.spyOn(authApi, "requestPasswordReset").mockResolvedValue({ status: "ok" });
    const user = userEvent.setup();
    renderWithClient();

    await user.type(screen.getByLabelText("Email"), "nobody@example.com");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));

    expect(
      await screen.findByText(/if an account exists for that email/i),
    ).toBeInTheDocument();
  });

  it("shows a retry time on rate limiting", async () => {
    vi.spyOn(authApi, "requestPasswordReset").mockRejectedValue(
      new RateLimitedError(60),
    );
    const user = userEvent.setup();
    renderWithClient();

    await user.type(screen.getByLabelText("Email"), "logan@logandapp.com");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/too many attempts/i);
    expect(await screen.findByRole("alert")).toHaveTextContent(/try again at/i);
  });
});
