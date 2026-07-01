// Shared Tailwind class strings enforcing the accessibility bar from
// docs/design/09-design-system.md ("elderly first-time user"): 44x44px
// minimum tap targets, 16px+ body text, visible focus rings. Centralized
// here so every interactive element across the app gets the same baseline
// instead of each component re-deriving the right padding/min-size by hand.
export const BUTTON_CLASS =
  "min-h-11 min-w-11 rounded border border-border bg-bg-secondary px-4 py-2 " +
  "text-base text-fg-primary hover:border-accent-orange focus-visible:outline " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 " +
  "focus-visible:outline-accent-orange disabled:cursor-not-allowed disabled:opacity-50";

export const INPUT_CLASS =
  "min-h-11 w-full rounded border border-border bg-bg-primary px-3 py-2 " +
  "text-base text-fg-primary focus-visible:outline focus-visible:outline-2 " +
  "focus-visible:outline-offset-2 focus-visible:outline-accent-orange";

export const LABEL_CLASS = "mb-1 block text-base text-fg-primary";

export const LINK_CLASS =
  "inline-flex min-h-11 items-center text-base text-accent-aqua underline " +
  "underline-offset-2 hover:text-accent-orange focus-visible:outline " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 " +
  "focus-visible:outline-accent-orange";

// Separate from LINK_CLASS -- in-content links (body copy, "click here to
// register") benefit from LINK_CLASS's permanent underline as a clear
// affordance that text is clickable, but a permanently-underlined,
// saturated-aqua row of links reads as dated/unstyled for primary site
// navigation ("make the links at the top look more professional"). Nav
// links here get an understated, muted color that brightens on
// hover/focus, with the underline appearing only then rather than always
// -- a common professional-site convention -- while keeping the same
// 44px tap target and visible focus ring the accessibility bar requires.
export const NAV_LINK_CLASS =
  "inline-flex min-h-11 items-center px-1 text-base tracking-wide text-fg-muted " +
  "no-underline transition-colors hover:text-accent-aqua hover:underline " +
  "underline-offset-4 focus-visible:text-accent-aqua focus-visible:outline " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 " +
  "focus-visible:outline-accent-orange";

// The brand/wordmark link specifically -- same interaction affordances as
// NAV_LINK_CLASS but visually distinct (brighter, no tracking) so it reads
// as the site's identity rather than just another nav item.
export const NAV_BRAND_CLASS =
  "inline-flex min-h-11 items-center text-base font-semibold text-fg-primary " +
  "no-underline transition-colors hover:text-accent-aqua focus-visible:outline " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 " +
  "focus-visible:outline-accent-orange";
