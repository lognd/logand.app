# 09 -- Design System

Audience: anyone making visual decisions -- typography, color, motion,
backgrounds, layout, accessibility. Read [00-overview.md](00-overview.md)
first. This doc is the single source of truth for "what should this
look like" -- don't make independent aesthetic calls in a feature doc or
PR, reference this one.

## Core directive: Ubuntu 22.04 terminal, ASCII-forward, hacker-box that anyone can use

The site should read as a terminal/shell environment (Ubuntu 22.04
specifically as the reference point: its default purple-and-orange
accent culture, monospace-forward feel, Yaru-adjacent iconography
language) rendered mostly in ASCII -- but the actual interaction model
must be obvious enough for someone who has never used a computer. These
two goals are reconciled like this: the *decoration* is terminal/ASCII
(backgrounds, headers, dividers, loading states), but every actual
control is a normal, large, clearly-labeled button/link/form -- never a
command the user has to type or memorize. Nothing interactive should
ever require typing a command to operate; the ASCII/terminal aesthetic
is skin, not input model.

## Typography

Avoid Inter/Roboto/Arial/system fonts and avoid Space Grotesk
specifically (named as an overused "creative" default to avoid).

- **Monospace (primary, body + UI chrome)**: `JetBrains Mono`. It's a
  deliberate fit, not an arbitrary pick -- it's literally the typeface
  shipped as the default in JetBrains IDEs, which ties back to this
  being delivered by a JetBrains-tooled, terminal-flavored agentic
  workflow, and it reads cleanly in ASCII-heavy layouts at small sizes.
- **Display (large headings only)**: `IBM Plex Mono` at a heavier
  weight for contrast against JetBrains Mono body text, or `Departure
  Mono` if a more raw/retro-terminal display face is wanted for hero
  text specifically -- pick one and use it consistently for H1/H2 only.
- No more than two font families total on the site.

## Color & theme

Base it on a real terminal color scheme rather than inventing one from
scratch -- **Gruvbox Dark** (warm, high-contrast, distinctly
non-corporate, avoids the cliche purple-gradient-on-white look the root
README explicitly warns against). Implement as CSS variables so a light
variant is swappable later without a rewrite:

```css
:root {
  --bg-primary:    #282828;
  --bg-secondary:  #3c3836;
  --fg-primary:    #ebdbb2;
  --fg-muted:       #a89984;
  --accent-orange:  #fe8019;   /* primary CTA / links */
  --accent-green:   #b8bb26;   /* success / paid status */
  --accent-red:     #fb4934;   /* errors / overdue status */
  --accent-aqua:    #8ec07c;   /* secondary accent */
  --border:          #504945;
}
```

Dominant dark background + one or two sharp accent colors (orange as
primary action color) per the root README's "dominant colors with sharp
accents" instruction -- not an evenly distributed rainbow palette.

A light theme is explicitly deferred, not abandoned: ship dark-only at
v1, structure tokens so a `data-theme="light"` swap is a CSS-variable
override later, not a rewrite (root README asks to "vary between light
and dark themes... across generations" but a single site only has one
default at a time -- pick dark for the terminal aesthetic, leave the
door open).

## Motion

- Library: Motion (React), per [07-frontend-architecture.md](07-frontend-architecture.md).
- One orchestrated page-load animation per route: staggered reveal of
  the ASCII header/background first, then nav, then content, using
  `animation-delay`-style staggering -- this is explicitly called out in
  the root README as higher-impact than scattered micro-interactions.
- Micro-interactions (button hover/press, form focus) use CSS
  transitions, not the Motion library -- keep JS-driven animation
  reserved for the one big orchestrated moment per page plus the ASCII
  canvas itself.
- Respect `prefers-reduced-motion`: the staggered page-load reveal
  collapses to a simple fade, ASCII background animation pauses on a
  static frame.

## Backgrounds

ASCII-rasterized gradient or generated-noise fields (see
[08-ascii-wasm-renderer.md](08-ascii-wasm-renderer.md)) layered behind
content at low opacity/contrast so they read as atmosphere, not noise
competing with text. Public-facing pages (landing, projects) get a more
prominent animated ASCII background; admin/customer authenticated views
use a quieter, mostly-static ASCII texture so it doesn't fight with
dense data tables (invoices, budget, inventory).

## Accessibility: "elderly first-time user" bar

This is a hard requirement, not a nice-to-have, and it overrides
aesthetic preference whenever the two conflict:

- Every interactive element is a labeled button/link with visible text
  -- never an icon-only control, never a control whose only affordance
  is a terminal-style blinking cursor prompt.
- Minimum tap/click target 44x44px (WCAG 2.5.5), minimum body text size
  16px even though the aesthetic is "terminal" -- terminals are
  traditionally small text, this site is not.
- Color is never the only signal (status badges get text labels, not
  just a color dot) -- contrast with [05-budget.md](05-budget.md) and
  [04-invoices.md](04-invoices.md) status fields, which must render as
  `<span>Paid</span>` styled green, not a bare colored dot.
- Full keyboard navigation and screen-reader labeling (semantic HTML,
  `aria-label`s on icon-adjacent buttons) -- this also directly serves
  the SEO/AI-agent-accessibility goal in
  [10-seo-and-agent-accessibility.md](10-seo-and-agent-accessibility.md),
  the two requirements reinforce each other.
- WCAG AA contrast minimum (4.5:1 body text) verified against the
  Gruvbox palette above for every text/background pairing actually
  used -- don't assume a themed palette is automatically accessible,
  check it.
- No auto-advancing carousels, no content that disappears on a timer
  without user action, no hover-only-revealed information (a non-mouse
  user, or someone whose hand shakes, must be able to access everything
  via click/tap).

## Testing

Visual regression and accessibility (axe/contrast) checks belong in the
frontend system-test layer -- see
[12-testing-strategy.md](12-testing-strategy.md).
