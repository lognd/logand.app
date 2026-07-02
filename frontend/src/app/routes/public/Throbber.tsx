// A small spinning-ring loading indicator (Tailwind's built-in
// animate-spin on a partial-stroke circle) plus a couple of pulsing
// "skeleton" bars standing in for text that hasn't loaded yet -- used by
// GithubRepoCard while its live api.github.com fetch is in flight, so
// "loading" reads as a real placeholder shape instead of just plain text.
export function Throbber({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      className={`animate-spin text-fg-muted ${className}`}
      aria-hidden
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}

// bg-border (not bg-bg-secondary) -- GithubRepoCard's own card background
// IS bg-bg-secondary, so a same-color skeleton bar would be invisible
// against it. border is the next step lighter in the Gruvbox scale, which
// reads clearly as "a bar" against the card without introducing a new
// color.
export function SkeletonLine({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-border ${className}`} />;
}
