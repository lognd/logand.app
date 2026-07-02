import { defineConfig, devices } from "@playwright/test";

// Requires the dev server (or a built preview server) running at baseURL.
// CI starts the full docker-compose.test.yml stack first -- see
// docs/design/12-testing-strategy.md and .github/workflows/ci.yml.
export default defineConfig({
  testDir: ".",
  // Absorbs one-off CI timing flake (a slow first real network round trip
  // against a freshly-started docker-compose.test.yml stack, cold JIT on
  // the very first test to run) without masking a genuinely broken test --
  // a real regression still fails after retrying too. 0 locally, since a
  // local failure should surface immediately, not silently retry.
  retries: process.env.CI ? 2 : 0,
  // Bumped from the 5000ms default for the same reason as `retries` above
  // -- CI's first assertion in the whole run is the one most likely to
  // catch a cold backend/frontend still warming up.
  expect: { timeout: 10_000 },
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
  // customer-journey.spec.ts registers 2+ real accounts per run against
  // auth/rate_limit.py's REGISTER bucket (5 per 15min per client, same
  // threshold as LOGIN, deliberately tight -- see that file's comment).
  // Running it on all three engines from the same CI runner IP burns
  // through that budget and starts 429ing mid-suite. Cross-browser
  // coverage still matters for real rendering/interaction differences
  // (landing.spec.ts's job, which does no account creation) -- the
  // register-heavy journey only needs to prove the flow works once, not
  // three times against a shared, intentionally-limited resource.
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    {
      name: "firefox",
      use: { ...devices["Desktop Firefox"] },
      testMatch: /landing\.spec\.ts/,
    },
    {
      name: "webkit",
      use: { ...devices["Desktop Safari"] },
      testMatch: /landing\.spec\.ts/,
    },
  ],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
  },
});
