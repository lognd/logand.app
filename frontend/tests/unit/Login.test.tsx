import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Login } from "../../src/app/routes/public/Login";
import * as authApi from "../../src/api/auth";
import { ApiError, RateLimitedError } from "../../src/api/client";

function renderWithClient() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Login", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders accessible, labeled email and password fields", () => {
    renderWithClient();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Log in" })).toBeInTheDocument();
  });

  it("calls the login API with the entered credentials on submit", async () => {
    const loginSpy = vi.spyOn(authApi, "login").mockResolvedValue({ status: "ok" });
    const user = userEvent.setup();
    renderWithClient();

    await user.type(screen.getByLabelText("Email"), "logan@logandapp.com");
    await user.type(screen.getByLabelText("Password"), "hunter2");
    await user.click(screen.getByRole("button", { name: "Log in" }));

    await waitFor(() => {
      expect(loginSpy).toHaveBeenCalledWith("logan@logandapp.com", "hunter2");
    });
  });

  it("shows an alert on a failed login", async () => {
    vi.spyOn(authApi, "login").mockRejectedValue(new Error("request failed: 401"));
    const user = userEvent.setup();
    renderWithClient();

    await user.type(screen.getByLabelText("Email"), "logan@logandapp.com");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/login failed/i);
  });

  it("shows the backend's real detail message on wrong credentials", async () => {
    vi.spyOn(authApi, "login").mockRejectedValue(
      new ApiError("email or password is incorrect", "AuthError.InvalidCredentials"),
    );
    const user = userEvent.setup();
    renderWithClient();

    await user.type(screen.getByLabelText("Email"), "logan@logandapp.com");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "email or password is incorrect",
    );
  });

  it("shows a retry time on rate limiting instead of a generic failure", async () => {
    vi.spyOn(authApi, "login").mockRejectedValue(new RateLimitedError(60));
    const user = userEvent.setup();
    renderWithClient();

    await user.type(screen.getByLabelText("Email"), "logan@logandapp.com");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/too many attempts/i);
    expect(await screen.findByRole("alert")).toHaveTextContent(/try again at/i);
  });

  it("shows a distinct message and resend link when the email is unverified", async () => {
    vi.spyOn(authApi, "login").mockRejectedValue(
      new ApiError(
        "please verify your email before logging in",
        "AuthError.EmailNotVerified",
      ),
    );
    const user = userEvent.setup();
    renderWithClient();

    await user.type(screen.getByLabelText("Email"), "unverified@example.com");
    await user.type(screen.getByLabelText("Password"), "the-real-password");
    await user.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "please verify your email before logging in",
    );
    const resendLink = screen.getByRole("link", { name: "Resend verification email" });
    expect(resendLink).toHaveAttribute(
      "href",
      "/verify-email?email=unverified%40example.com",
    );
  });

  it("links to the forgot-password page", () => {
    renderWithClient();
    expect(screen.getByRole("link", { name: "Forgot your password?" })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
  });
});
