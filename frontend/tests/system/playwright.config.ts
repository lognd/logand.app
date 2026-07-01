import { defineConfig, devices } from "@playwright/test";

// Requires the dev server (or a built preview server) running at baseURL.
// CI starts the full docker-compose.test.yml stack first -- see
// docs/design/12-testing-strategy.md and .github/workflows/ci.yml.
export default defineConfig({
  testDir: ".",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173",
  },
  // Previously no `projects` array at all, which meant every system test
  // only ever ran under Playwright's default Chromium -- Firefox and
  // Safari/WebKit (the two other engines real visitors show up in) had
  // zero coverage despite this being the layer specifically meant to
  // catch real-browser-contract bugs (docs/design/12-testing-strategy.md).
  // "chromium" is kept first/default so `npx playwright test --project
  // chromium` (or no --project flag during local dev, which runs all
  // three) still works the way it always did.
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
  },
});
