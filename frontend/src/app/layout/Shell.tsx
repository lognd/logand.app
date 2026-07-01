import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AsciiCanvas } from "../../ascii/AsciiCanvas";
import { NAV_BRAND_CLASS, NAV_LINK_CLASS } from "../../styles/a11y";
import { logout } from "../../api/auth";
import { useMe } from "../../hooks/useMe";

function NavLinks({ className }: { className?: string }) {
  const { data: me, isLoading } = useMe();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const logoutMutation = useMutation({
    mutationFn: logout,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      navigate("/");
    },
  });

  // Don't flash "log in" before the very first /api/me resolves -- render
  // nothing in that brief window rather than a guess that's wrong half the
  // time.
  if (isLoading) return null;

  if (!me) {
    return (
      <>
        <a href="/login" className={`${NAV_LINK_CLASS} ${className ?? ""}`}>
          log in
        </a>
        <a href="/register" className={`${NAV_LINK_CLASS} ${className ?? ""}`}>
          register
        </a>
      </>
    );
  }

  return (
    <>
      {me.role === "admin" && (
        <>
          <a href="/admin/invoices" className={`${NAV_LINK_CLASS} ${className ?? ""}`}>
            invoices
          </a>
          <a href="/admin/budget" className={`${NAV_LINK_CLASS} ${className ?? ""}`}>
            budget
          </a>
          <a href="/admin/inventory" className={`${NAV_LINK_CLASS} ${className ?? ""}`}>
            inventory
          </a>
        </>
      )}
      {me.role === "customer" && (
        <a href="/invoices" className={`${NAV_LINK_CLASS} ${className ?? ""}`}>
          my invoices
        </a>
      )}
      <button
        type="button"
        className={`${NAV_LINK_CLASS} ${className ?? ""}`}
        onClick={() => logoutMutation.mutate()}
        disabled={logoutMutation.isPending}
      >
        log out
      </button>
    </>
  );
}

// Primary nav links (not the account-state-dependent NavLinks above) --
// shared between the desktop inline row and the mobile dropdown so the
// two can't drift out of sync.
function PrimaryLinks({ className }: { className?: string }) {
  return (
    <>
      <a href="/projects" className={`${NAV_LINK_CLASS} ${className ?? ""}`}>
        projects
      </a>
      <a href="/contact" className={`${NAV_LINK_CLASS} ${className ?? ""}`}>
        contact
      </a>
    </>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
    // flex flex-col, not just min-h-screen: a plain min-h-screen root PLUS
    // a min-h-screen <main> further down (Landing.tsx) double-counts height
    // (header height + 100vh for main = more than 100vh total), producing a
    // permanent vertical scrollbar even with nothing actually overflowing.
    // With flex-col + the content wrapper below set to flex-1, the content
    // area exactly fills "100vh minus header height", so a child that also
    // wants to fill its container (Landing's <main className="h-full">)
    // does so without exceeding the viewport.
    <div className="relative isolate flex min-h-screen flex-col bg-bg-primary text-fg-primary">
      {/* `isolate` is load-bearing, not decorative: without it this div doesn't
          establish its own stacking context (position:relative + no z-index
          doesn't), so its own bg-bg-primary paints OVER any negative-z-index
          descendant anywhere in the subtree (including Landing's
          SpinningShape) instead of below it -- the background layers were
          fully invisible until this was added. */}
      {/* Atmosphere layer, see docs/design/09 -- low-opacity, never competes
          with content. Dropped from opacity-20 after feedback that the
          combined background (this + Landing's SpinningShape stacked on
          top) read as distracting. */}
      <AsciiCanvas className="pointer-events-none fixed inset-0 -z-10 opacity-10" />
      <header className="relative z-20 border-b border-border">
        <div className="flex items-center justify-between gap-4 p-4">
          <a href="/" className={NAV_BRAND_CLASS}>
            logand.app
          </a>
          {/* Desktop/wide nav: everything inline in one row. Hidden below
              `sm` -- at phone widths this exact row is what wrapped onto a
              cramped, uneven second line ("the header gets scrunched up"),
              since there just isn't room for brand + 2 primary links + 2
              account links side by side. */}
          <nav aria-label="primary" className="hidden items-center gap-6 sm:flex">
            <PrimaryLinks />
            <NavLinks />
          </nav>
          {/* Mobile toggle: replaces the cramped wrapped row with a single
              deliberate control. aria-expanded/aria-controls tie it to the
              dropdown panel below for assistive tech. */}
          <button
            type="button"
            // Plain ASCII text label, not a glyph/icon -- keeps this
            // legible and unambiguous rather than relying on a Unicode
            // hamburger/close glyph that isn't guaranteed to render
            // identically (or at the same width) across fonts.
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded px-3 text-base text-fg-primary hover:text-accent-aqua focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-orange sm:hidden"
            aria-expanded={mobileNavOpen}
            aria-controls="mobile-nav"
            onClick={() => setMobileNavOpen((open) => !open)}
          >
            {mobileNavOpen ? "Close" : "Menu"}
          </button>
        </div>
        {mobileNavOpen && (
          <nav
            id="mobile-nav"
            aria-label="primary"
            className="flex flex-col gap-1 border-t border-border p-4 sm:hidden"
          >
            <PrimaryLinks className="w-full" />
            <NavLinks className="w-full" />
          </nav>
        )}
      </header>
      <div className="relative z-10 flex-1">{children}</div>
    </div>
  );
}
