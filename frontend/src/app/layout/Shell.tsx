import type { ReactNode } from "react";
import { AsciiCanvas } from "../../ascii/AsciiCanvas";

export function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="relative min-h-screen">
      {/* Atmosphere layer, see docs/design/09 -- low-opacity, never competes with content. */}
      <AsciiCanvas className="pointer-events-none fixed inset-0 -z-10 opacity-20" />
      <header className="border-b border-border p-4">
        <nav aria-label="primary" className="flex gap-4">
          <a href="/">logand.app</a>
          <a href="/projects">projects</a>
          <a href="/contact">contact</a>
        </nav>
      </header>
      {children}
    </div>
  );
}
