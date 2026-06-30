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
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/unit/**/*.test.ts", "tests/unit/**/*.test.tsx"],
  },
});
