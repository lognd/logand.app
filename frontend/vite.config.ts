import { existsSync, rmSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// public/mockServiceWorker.js is only needed for `npm run dev:mock` (MSW's
// dev-server-serves-it-statically requirement) -- Vite's publicDir copies
// EVERYTHING in public/ into dist/ on every build regardless of mode, which
// would otherwise leave a dead-but-present mock worker script in every
// production deploy. Strip it back out after a real (non-mock) build so
// "mocks never ship in production" is actually true of the build output,
// not just of the JS bundle (the JS side is already gated behind
// VITE_USE_MOCKS in main.tsx, dynamically imported so it's tree-shaken out
// -- this plugin closes the remaining static-asset gap).
function stripMockWorkerFromBuild() {
  return {
    name: "strip-mock-worker-from-production-build",
    apply: "build" as const,
    closeBundle() {
      if (process.env.VITE_USE_MOCKS === "true") return;
      const target = resolve(__dirname, "dist/mockServiceWorker.js");
      if (existsSync(target)) rmSync(target);
    },
  };
}

export default defineConfig({
  plugins: [react(), stripMockWorkerFromBuild()],
  resolve: {
    alias: {
      "@": "/src",
    },
  },
  server: {
    port: 5173,
    // api/client.ts only ever fetches relative paths ("/api/...", see
    // its own doc comment) -- fine for a real deployment (frontend and
    // backend served from the same origin behind Caddy, per
    // docs/design/11), but the plain `vite dev` server has nothing to
    // forward those to on its own. This was a latent gap: no existing
    // frontend system test actually called the API (landing.spec.ts just
    // checks static content), so it went unnoticed. Proxying to the
    // backend's real port here -- overridable via
    // VITE_API_PROXY_TARGET for CI's docker-compose.test.yml stack,
    // where the backend isn't necessarily on localhost:8000 -- is what
    // makes a system test that actually registers/logs in/pays an
    // invoice reach a real backend instead of 404ing against the dev
    // server itself.
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/unit/**/*.test.ts", "tests/unit/**/*.test.tsx"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["src/**/*.{ts,tsx}"],
      // mocks/ only exists to be loaded BY tests (see its own top-of-file
      // doc comment) -- test infrastructure, not application code, same
      // reasoning as the backend's coverage config excluding
      // testing/fake_*.py.
      exclude: ["src/mocks/**", "**/*.d.ts"],
    },
  },
});
