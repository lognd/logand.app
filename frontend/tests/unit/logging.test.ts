import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  clearLogEntries,
  formatLogsForExport,
  getLogEntries,
  logError,
  logInfo,
} from "../../src/lib/logging";

describe("client-side logging (lib/logging.ts)", () => {
  beforeEach(() => {
    localStorage.clear();
    clearLogEntries();
  });
  afterEach(() => {
    clearLogEntries();
  });

  it("records entries and returns them in order", () => {
    logInfo("first");
    logError("second", "with detail");

    const entries = getLogEntries();
    expect(entries).toHaveLength(2);
    expect(entries[0].message).toBe("first");
    expect(entries[1].level).toBe("error");
    expect(entries[1].detail).toBe("with detail");
  });

  it("never grows past the bounded ring-buffer size", () => {
    for (let i = 0; i < 700; i++) {
      logInfo(`entry ${i}`);
    }
    const entries = getLogEntries();
    expect(entries.length).toBeLessThanOrEqual(500);
    // Oldest entries dropped first -- the buffer keeps the MOST RECENT
    // ones, which is what matters for a crash report.
    expect(entries[entries.length - 1].message).toBe("entry 699");
  });

  it("persists across a simulated reload via localStorage", () => {
    logInfo("persisted entry");
    const stored = localStorage.getItem("logand.clientLogs");
    expect(stored).toContain("persisted entry");
  });

  it("clearLogEntries empties both memory and storage", () => {
    logInfo("will be cleared");
    clearLogEntries();
    expect(getLogEntries()).toHaveLength(0);
    expect(localStorage.getItem("logand.clientLogs")).toBe("[]");
  });

  it("formatLogsForExport produces a readable, self-contained report", () => {
    logError("boom", "stack trace here");
    const report = formatLogsForExport();
    expect(report).toContain("logand.app client log export");
    expect(report).toContain("[ERROR] boom");
    expect(report).toContain("stack trace here");
  });
});
