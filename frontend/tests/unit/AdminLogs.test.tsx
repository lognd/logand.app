import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AdminLogs } from "../../src/app/routes/admin/AdminLogs";

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
      <AdminLogs />
    </QueryClientProvider>,
  );
}

describe("AdminLogs (integration)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists real log files with working download links and shows the live tail", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/admin/logs/files") {
        return Promise.resolve(
          jsonResponse([
            { name: "app.log", size_bytes: 2048, modified_at: 1700000000 },
          ]),
        );
      }
      if (url.startsWith("/api/admin/logs/tail")) {
        return Promise.resolve(jsonResponse(['{"level":"INFO"}']));
      }
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    expect(await screen.findByText(/app\.log/)).toBeInTheDocument();
    const downloadLink = await screen.findByRole("link", { name: "Download" });
    expect(downloadLink).toHaveAttribute("href", "/api/admin/logs/files/app.log");
    expect(await screen.findByText(/"level":"INFO"/)).toBeInTheDocument();
  });
});
