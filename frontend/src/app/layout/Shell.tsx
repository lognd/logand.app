import { useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AsciiCanvas } from "../../ascii/AsciiCanvas";
import { NAV_BRAND_CLASS, NAV_LINK_CLASS } from "../../styles/a11y";
import { logout } from "../../api/auth";
import { useMe } from "../../hooks/useMe";
import { GlitchText } from "./GlitchText";
import { ReportProblemButton } from "./ReportProblemButton";

function NavLinks({ className }: { className?: string }) {
  const { data: me, isLoading } = useMe();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const logoutMutation = useMutation({
    mutationFn: logout,
    onSuccess: async () => {
      // setQueryData(null) FIRST, not just invalidateQueries -- react-query
      // keeps the last successful `data` around when a refetch errors (the
      // /api/me call this invalidation triggers now 401s, since the session
      // is actually gone), so invalidateQueries alone left `me` (and thus
      // the nav) showing the just-logged-out user's stale session until an
      // unrelated full page reload happened to clear it -- confirmed via a
      // real logout against a real backend, not just the mocked test
      // fixtures, which never exercised this specific stale-cache case.
      // Setting it to null directly makes NavLinks' `!me` check flip
      // immediately; invalidateQueries after that still forces a real
      // background recheck for consistency.
      queryClient.setQueryData(["me"], null);
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      navigate("/");
    },
  });

  // Only ever hide these links before the VERY FIRST /api/me resolves,
  // never again after that -- react-query's default refetchOnWindowFocus
  // refetches /api/me every time the tab regains focus (e.g. alt-tabbing
  // back), and isLoading goes true again for that background refetch too
  // ("the header links still flash when I alt+tab"). Once we've rendered
  // real content once, a ref (not state, so this doesn't itself trigger a
  // re-render) remembers that, so a later refetch keeps showing the last-
  // known links instead of blanking them out while it's in flight.
  const hasLoadedOnceRef = useRef(false);
  if (!isLoading) hasLoadedOnceRef.current = true;
  if (isLoading && !hasLoadedOnceRef.current) return null;

  if (!me) {
    return (
      <>
        <a href="/login" aria-label="log in" className={`${NAV_LINK_CLASS} ${className ?? ""}`}>
          <GlitchText>log in</GlitchText>
        </a>
        <a
          href="/register"
          aria-label="register"
          className={`${NAV_LINK_CLASS} ${className ?? ""}`}
        >
          <GlitchText>register</GlitchText>
        </a>
      </>
    );
  }

  return (
    <>
      {/* Both roles now get a single nav link to their portal landing page
          (/admin, /portal) rather than linking straight to invoicing --
          budget and inventory are reachable from the admin portal page
          itself, not from this top nav directly. */}
      {me.role === "admin" && (
        <a
          href="/admin"
          aria-label="admin portal"
          className={`${NAV_LINK_CLASS} ${className ?? ""}`}
        >
          <GlitchText>portal</GlitchText>
        </a>
      )}
      {me.role === "customer" && (
        <a
          href="/portal"
          aria-label="your account"
          className={`${NAV_LINK_CLASS} ${className ?? ""}`}
        >
          <GlitchText>portal</GlitchText>
        </a>
      )}
      <button
        type="button"
        aria-label="log out"
        className={`${NAV_LINK_CLASS} ${className ?? ""}`}
        onClick={() => logoutMutation.mutate()}
        disabled={logoutMutation.isPending}
      >
        <GlitchText>log out</GlitchText>
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
      <a href="/projects" aria-label="projects" className={`${NAV_LINK_CLASS} ${className ?? ""}`}>
        <GlitchText>projects</GlitchText>
      </a>
      <a href="/contact" aria-label="contact" className={`${NAV_LINK_CLASS} ${className ?? ""}`}>
        <GlitchText>contact</GlitchText>
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
    // min-h-svh (SMALLEST viewport height), not min-h-screen (100vh) and
    // not min-h-dvh either -- 100vh is measured against the LARGEST
    // possible viewport (address bar hidden), so with the address bar
    // visible (the common case) an element sized to 100vh is taller than
    // what's actually visible, forcing a scrollbar/overflow that has
    // nothing to do with real content ("the overflow is busted on
    // mobile"). dvh (dynamic viewport height) was tried next, on the
    // assumption it tracks the CURRENT viewport size as toolbars show/
    // hide -- but that tracking is exactly where mobile Firefox and
    // Chrome disagree (confirmed: same layout was correctly sized on
    // Chrome mobile but scrollable on Firefox mobile), since dvh's
    // resize-driven recalculation isn't implemented identically across
    // engines. svh is always pinned to the SMALLEST the viewport can
    // ever be (toolbars fully expanded) -- guaranteed to fit inside the
    // visible area on every browser regardless of toolbar state or how
    // faithfully that engine recomputes dvh, at the cost of a few pixels
    // of unused space at the very bottom on a browser that DOES hide its
    // toolbar and DOES recompute dvh correctly. Trading a harmless gap
    // for guaranteed no-scrollbar is the right side of that tradeoff.
    <div className="relative isolate flex min-h-svh flex-col bg-bg-primary text-fg-primary">
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
      <ReportProblemButton />
      {/* glass-panel, not a plain border -- ParticleLayer (Landing.tsx) is a
          `fixed` element also covering the header ("enable it on the
          header"), and this header used to have no background at all
          (just border-b), so the trail/explosion painted straight through
          the nav text completely unblurred. glass-panel's translucent +
          backdrop-blur background keeps the nav legible while letting
          whatever's passing underneath show through softened, same
          treatment as Landing's footer. */}
      <header className="glass-panel relative z-20 border-b">
        <div className="flex items-center justify-between gap-4 p-4">
          <a href="/" aria-label="logand.app" className={NAV_BRAND_CLASS}>
            <GlitchText>logand.app</GlitchText>
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
        {/* Always mounted, visibility toggled with `hidden` -- not
            `{mobileNavOpen && (...)}` (conditionally rendering the JSX,
            tried first). Conditionally rendering destroys and recreates
            NavLinks as a brand new component instance every time the
            menu opens, which loses NavLinks' own "have we ever finished
            loading" ref (see that component's doc comment for the
            alt-tab refetch-flash bug this same ref fixes) -- a fresh
            instance starts that ref back at false, so opening the menu
            again could re-trigger the exact same blank flash this was
            just fixed for elsewhere ("the menu open/close now has the
            same flashing bug as the main site earlier"). Keeping one
            persistent instance mounted the whole time means that ref
            (and the fact that /api/me already resolved once) survives
            across every open/close.
            `hidden` (not just clipping via max-h-0, say) also fully
            removes it from layout and the accessibility tree while
            closed, same as it not being rendered at all would have. */}
        <nav
          id="mobile-nav"
          aria-label="primary"
          // hidden via the CONDITIONAL CLASS below (`hidden` utility vs
          // `flex`), not the native `hidden` attribute -- the attribute's
          // `[hidden]{display:none}` rule lives in the browser's lowest-
          // priority default stylesheet, which this element's own `flex`
          // utility class (an author-stylesheet rule) would silently
          // override regardless of specificity, leaving it visible
          // anyway. Swapping the display utility itself avoids that.
          // `aria-hidden` still needs to reflect closed state directly
          // for assistive tech, since `display:none` via a class (rather
          // than the `hidden` attribute) doesn't imply it on its own.
          aria-hidden={!mobileNavOpen}
          // `absolute` overlay, not normal flow -- a normal-flow dropdown
          // grows the header's own box height while open, which (with
          // several stacked links, e.g. an admin's full link list) could
          // push the page's total height past the viewport, forcing a
          // page-level scrollbar just from opening the menu ("I want menu
          // to not extend the page and make it scrollable"). Positioned
          // absolutely below the header instead, so opening it never
          // changes any other element's layout; `max-h-[70dvh]` +
          // `overflow-y-auto` make the PANEL ITSELF scrollable if its own
          // content (an admin's full nav list, say) is taller than that,
          // rather than the page growing to fit it.
          //
          // Background/border switched from solid bg-bg-primary/border-border
          // to the shared .glass-panel treatment ("an incredibly thin
          // border as well as like 70%-ish opacity" -- see tailwind.css's
          // .glass-panel for why this is a plain CSS class rather than
          // Tailwind's bg-x/NN opacity-modifier syntax, which tokens.css's
          // plain-hex colors don't support). border-b (in addition to the
          // existing border-t) -- "there needs to be a thin bottom border
          // on the menu popdown, so it doesn't immediately jut out" against
          // whatever's below it once it's open.
          className={`glass-panel absolute inset-x-0 top-full z-30 ${
            mobileNavOpen ? "flex" : "hidden"
          } max-h-[70dvh] flex-col gap-1 overflow-y-auto border-b border-t p-4 sm:hidden`}
        >
          <PrimaryLinks className="w-full" />
          <NavLinks className="w-full" />
        </nav>
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
