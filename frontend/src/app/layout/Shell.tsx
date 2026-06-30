import type { ReactNode } from "react";
import { AsciiCanvas } from "../../ascii/AsciiCanvas";
import { LINK_CLASS } from "../../styles/a11y";

export function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="relative min-h-screen bg-bg-primary text-fg-primary">
      {/* Atmosphere layer, see docs/design/09 -- low-opacity, never competes with content. */}
      <AsciiCanvas className="pointer-events-none fixed inset-0 -z-10 opacity-20" />
      <header className="border-b border-border p-4">
        <nav aria-label="primary" className="flex flex-wrap gap-4">
          <a href="/" className={LINK_CLASS}>
            logand.app
          </a>
          <a href="/projects" className={LINK_CLASS}>
            projects
          </a>
          <a href="/contact" className={LINK_CLASS}>
            contact
          </a>
        </nav>
      </header>
      {children}
    </div>
  );
}
