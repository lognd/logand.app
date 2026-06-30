import type { ReactNode } from "react";
import { AsciiCanvas } from "../../ascii/AsciiCanvas";
import { LINK_CLASS } from "../../styles/a11y";

export function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="relative isolate min-h-screen bg-bg-primary text-fg-primary">
      {/* `isolate` is load-bearing, not decorative: without it this div doesn't
          establish its own stacking context (position:relative + no z-index
          doesn't), so its own bg-bg-primary paints OVER any negative-z-index
          descendant anywhere in the subtree (including Landing's
          SpinningShape) instead of below it -- the background layers were
          fully invisible until this was added. */}
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
