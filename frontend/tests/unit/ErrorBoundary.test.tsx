import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "../../src/app/layout/ErrorBoundary";
import { clearLogEntries, getLogEntries } from "../../src/lib/logging";

function Bomb(): never {
  throw new Error("deliberate render crash");
}

describe("ErrorBoundary", () => {
  it("catches a render crash, logs it, and shows a working download button", () => {
    clearLogEntries();
    // React logs the error to console.error itself too -- silence that
    // expected noise so the test output stays readable.
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );

    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download logs" })).toBeInTheDocument();

    const entries = getLogEntries();
    expect(entries.some((e) => e.message === "React render crash")).toBe(true);
    expect(entries.some((e) => e.detail?.includes("deliberate render crash"))).toBe(
      true,
    );

    consoleSpy.mockRestore();
  });
});
