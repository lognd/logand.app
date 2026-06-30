import type { Config } from "tailwindcss";

// Tailwind reads color values from the CSS variables defined in
// src/styles/tokens.css (Gruvbox Dark palette, see docs/design/09-design-system.md).
// Keep this file's palette names in sync with tokens.css var names.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        "bg-primary": "var(--bg-primary)",
        "bg-secondary": "var(--bg-secondary)",
        "fg-primary": "var(--fg-primary)",
        "fg-muted": "var(--fg-muted)",
        "accent-orange": "var(--accent-orange)",
        "accent-green": "var(--accent-green)",
        "accent-red": "var(--accent-red)",
        "accent-aqua": "var(--accent-aqua)",
        border: "var(--border)",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
        display: ["IBM Plex Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
