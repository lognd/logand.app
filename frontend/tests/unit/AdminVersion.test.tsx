import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AdminVersion } from "../../src/app/routes/admin/AdminVersion";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminVersion />
    </QueryClientProvider>,
  );
}

describe("AdminVersion (integration)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the real app version, git commit, and dependency list", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        jsonResponse({
          app_version: "0.1.0",
          git_commit: "abc1234",
          python_version: "3.12.0",
          platform: "Linux-test",
          dependencies: { fastapi: "0.111.0" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    expect(await screen.findByText("abc1234")).toBeInTheDocument();
    expect(await screen.findByText("0.1.0")).toBeInTheDocument();
    expect(await screen.findByText("fastapi")).toBeInTheDocument();
    expect(await screen.findByText("0.111.0")).toBeInTheDocument();
  });
});
