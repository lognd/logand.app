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
