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
    // flex flex-col, not just min-h-dvh: a plain min-h-dvh root PLUS
    // a min-h-dvh <main> further down (Landing.tsx) double-counts height
    // (header height + 100dvh for main = more than 100dvh total), producing a
    // permanent vertical scrollbar even with nothing actually overflowing.
    // With flex-col + the content wrapper below set to flex-1, the content
    // area exactly fills "100dvh minus header height", so a child that also
    // wants to fill its container (Landing's <main className="h-full">)
    // does so without exceeding the viewport.
    //
    // min-h-dvh (dynamic viewport height), not min-h-screen (100vh) -- on
    // mobile browsers, 100vh is measured against the LARGEST possible
    // viewport (address bar hidden), so with the address bar visible
    // (the common case) an element sized to 100vh is taller than what's
    // actually visible, forcing a scrollbar/overflow that has nothing to
    // do with real content ("the overflow is busted on mobile"). 100dvh
    // tracks the viewport's actual current size, address bar and all.
    <div className="relative isolate flex min-h-dvh flex-col bg-bg-primary text-fg-primary">
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
      {/* `flex flex-col`, not a plain block box -- Landing.tsx's <main>
          used to size itself via `h-full` (height:100%), which needs this
          wrapper to have a genuinely DEFINITE height for that percentage
          to resolve against. This wrapper's own height comes from
          flex-grow (flex-1) on the shell-root flex column above, and
          while getComputedStyle correctly reports a real pixel height for
          it, a flex-grown size along the main axis isn't always treated
          as "definite" for a DESCENDANT's percentage-height resolution
          the way an explicit `height` would be -- in practice this left
          <main> sized to fit its own content instead of stretching to
          fill the actual remaining space, so its footer landed partway up
          the page instead of at the true bottom ("you moved the footer
          upwards," "content sizes to the minimum containing size").
          Making this wrapper a flex container itself and having <main> use
          flex-1 (not h-full) sidesteps percentage-height resolution
          entirely -- flex-grow distribution is what flexbox is actually
          built to do reliably. */}
      <div className="relative z-10 flex flex-1 flex-col">{children}</div>
    </div>
  );
}
