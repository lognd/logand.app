import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Register } from "../../src/app/routes/public/Register";
import * as authApi from "../../src/api/auth";
import { RateLimitedError } from "../../src/api/client";

function renderWithClient() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Register />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Register", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls register with only the entered email (FINDINGS H1: no password)", async () => {
    const registerSpy = vi
      .spyOn(authApi, "register")
      .mockResolvedValue({ status: "ok" });
    const user = userEvent.setup();
    renderWithClient();

    // There is no password field at registration any more.
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Email"), "logan@logandapp.com");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => {
      expect(registerSpy).toHaveBeenCalledWith("logan@logandapp.com");
    });
  });

  it("shows a check-your-email message instead of logging the visitor in (docs/design/17)", async () => {
    vi.spyOn(authApi, "register").mockResolvedValue({ status: "ok" });
    const user = userEvent.setup();
    renderWithClient();

    await user.type(screen.getByLabelText("Email"), "logan@logandapp.com");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(
      await screen.findByText(/check your email for a link to verify your account/i),
    ).toBeInTheDocument();
    // Registration no longer logs the visitor in -- there is no form left
    // to re-submit and no redirect away from this page.
    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
  });

  it("shows a retry time on rate limiting instead of a generic failure", async () => {
    vi.spyOn(authApi, "register").mockRejectedValue(new RateLimitedError(60));
    const user = userEvent.setup();
    renderWithClient();

    await user.type(screen.getByLabelText("Email"), "logan@logandapp.com");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/too many attempts/i);
    expect(await screen.findByRole("alert")).toHaveTextContent(/try again at/i);
  });
});
