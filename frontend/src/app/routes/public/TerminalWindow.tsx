import { useEffect, useRef, useState } from "react";

// A real, live-rendered terminal window -- not a screenshot image -- for
// project cards that want to show actual CLI/REPL output (frob, typani).
// Renders crisp at any size/DPI and scales with its container instead of
// being a fixed-resolution raster the carousel has to shrink or upscale.
//
// Styled to read as Ubuntu's GNOME window chrome, not macOS's: window
// controls sit on the RIGHT (Ubuntu's default GNOME Shell placement,
// opposite of macOS's left-side traffic lights) and are plain monochrome
// outline glyphs, not solid colored circles -- "make it look more like
// Ubuntu... I don't want it to look like Mac."
export interface TerminalLine {
  kind: "prompt" | "out" | "muted" | "accent";
  text: string;
}

const LINE_COLOR: Record<TerminalLine["kind"], string> = {
  prompt: "text-accent-green",
  out: "text-fg-primary",
  muted: "text-fg-muted",
  accent: "text-accent-aqua",
};

function WindowControlIcon({ kind }: { kind: "minimize" | "maximize" | "close" }) {
  return (
    <svg viewBox="0 0 12 12" className="h-3 w-3" stroke="currentColor" strokeWidth={1.3} fill="none">
      {kind === "minimize" && <path d="M2 9h8" strokeLinecap="round" />}
      {kind === "maximize" && <rect x="2.5" y="2.5" width="7" height="7" rx="0.5" />}
      {kind === "close" && <path d="M2.5 2.5l7 7M9.5 2.5l-7 7" strokeLinecap="round" />}
    </svg>
  );
}

export function TerminalWindow({ title, lines }: { title: string; lines: TerminalLine[] }) {
  const bodyRef = useRef<HTMLDivElement | null>(null);
  // Whether there's more content below the fold -- gates whether the
  // scroll hint can ever appear at all (see the `group`/opacity treatment
  // below for the actual show/hide behavior).
  const [hasMore, setHasMore] = useState(false);

  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    function check() {
      if (!el) return;
      setHasMore(el.scrollHeight - el.scrollTop - el.clientHeight > 4);
    }
    check();
    el.addEventListener("scroll", check);
    const observer = new ResizeObserver(check);
    observer.observe(el);
    return () => {
      el.removeEventListener("scroll", check);
      observer.disconnect();
    };
  }, [lines]);

  return (
    // `group` -- the hint below is a CSS opacity transition keyed off
    // this element's own :hover (group-hover), not a JS timer that shows
    // it outright the moment the delay elapses. That's what makes it
    // actually fade in/out smoothly on hover/unhover instead of popping
    // in and out instantly ("have it fade in and out rather than appear
    // instantly").
    <div className="group relative flex h-full w-full flex-col overflow-hidden bg-bg-primary">
      {/* Titlebar: title left, controls right (Ubuntu GNOME order),
          monochrome outline glyphs instead of macOS's solid red/yellow/
          green dots. */}
      <div className="flex shrink-0 items-center justify-between border-b border-border bg-bg-secondary px-3 py-1.5">
        <span className="truncate font-mono text-xs text-fg-secondary">{title}</span>
        <div className="flex shrink-0 items-center gap-3 text-fg-muted">
          <WindowControlIcon kind="minimize" />
          <WindowControlIcon kind="maximize" />
          <WindowControlIcon kind="close" />
        </div>
      </div>
      {/* overflow-x-auto + whitespace-pre (not pre-wrap) -- these lines
          are column-aligned with literal padding spaces (frob's
          map/check tables); wrapping a padded line onto a second visual
          line destroys that alignment entirely ("line wrapping is
          messing up the terminal"). A real terminal doesn't reflow long
          lines either -- it lets them run off the edge and scrolls --
          so this matches that instead of fighting it. w-max on the <pre>
          lets it grow wider than the container so overflow-x-auto has
          something real to scroll.
          text-xs + leading-snug (down from 13px/1.5) -- smaller and
          tighter reads more like an actual terminal at this box size,
          and fits more real output before scrolling is even needed. */}
      <div ref={bodyRef} className="min-h-0 flex-1 overflow-x-auto overflow-y-auto no-scrollbar px-3 py-2">
        <pre className="w-max min-w-full whitespace-pre font-mono text-xs leading-snug">
          {lines.map((line, i) => (
            <div key={i} className={LINE_COLOR[line.kind]}>
              {line.text || " "}
            </div>
          ))}
        </pre>
      </div>
      {hasMore && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 bottom-0 flex h-8 items-end justify-center gap-1 bg-gradient-to-t from-bg-primary to-transparent pb-0.5 opacity-0 transition-opacity duration-300 group-hover:opacity-100"
        >
          <span className="font-mono text-[10px] text-fg-muted">scroll for more</span>
          <svg viewBox="0 0 16 8" className="h-2 w-4 animate-bounce text-fg-muted" fill="currentColor">
            <path d="M0 0l8 8 8-8z" />
          </svg>
        </div>
      )}
    </div>
  );
}
