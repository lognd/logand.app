import { defineConfig } from "@playwright/test";

// Requires the dev server (or a built preview server) running at baseURL.
// CI starts the full docker-compose.test.yml stack first -- see
// docs/design/12-testing-strategy.md and .github/workflows/ci.yml.
export default defineConfig({
  testDir: ".",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173",
  },
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
  },
});
