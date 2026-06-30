import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AsciiCanvas } from "../../ascii/AsciiCanvas";
import { LINK_CLASS } from "../../styles/a11y";
import { logout } from "../../api/auth";
import { useMe } from "../../hooks/useMe";

function NavLinks() {
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
        <a href="/login" className={LINK_CLASS}>
          log in
        </a>
        <a href="/register" className={LINK_CLASS}>
          register
        </a>
      </>
    );
  }

  return (
    <>
      {me.role === "admin" && (
        <>
          <a href="/admin/invoices" className={LINK_CLASS}>
            invoices
          </a>
          <a href="/admin/budget" className={LINK_CLASS}>
            budget
          </a>
          <a href="/admin/inventory" className={LINK_CLASS}>
            inventory
          </a>
        </>
      )}
      {me.role === "customer" && (
        <a href="/invoices" className={LINK_CLASS}>
          my invoices
        </a>
      )}
      <button
        type="button"
        className={LINK_CLASS}
        onClick={() => logoutMutation.mutate()}
        disabled={logoutMutation.isPending}
      >
        log out
      </button>
    </>
  );
}

export function Shell({ children }: { children: ReactNode }) {
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
      <header className="relative z-10 border-b border-border p-4">
        <nav aria-label="primary" className="flex flex-wrap items-center gap-4">
          <a href="/" className={LINK_CLASS}>
            logand.app
          </a>
          <a href="/projects" className={LINK_CLASS}>
            projects
          </a>
          <a href="/contact" className={LINK_CLASS}>
            contact
          </a>
          <span className="flex-1" />
          <NavLinks />
        </nav>
      </header>
      <div className="relative z-10 flex-1">{children}</div>
    </div>
  );
}
