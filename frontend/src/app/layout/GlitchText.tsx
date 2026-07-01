import { useEffect, useRef, useState } from "react";

// Printable ASCII "glitch" glyphs -- not letters/digits, so a substituted
// character always reads as visibly "wrong" rather than accidentally
// spelling a different real word.
const GLITCH_CHARS = "!<>-_\\/[]{}=+*^?#&$~";
const GLITCH_DURATION_MS = 400;
const GLITCH_FRAME_MS = 40;
// Fraction of (non-space) characters swapped for a glitch glyph on any
// given frame -- low enough that the original word stays legible through
// the effect instead of becoming full noise.
const SUBSTITUTION_RATE = 0.35;

function scramble(text: string): string {
  return [...text]
    .map((ch) =>
      ch !== " " && Math.random() < SUBSTITUTION_RATE
        ? GLITCH_CHARS[Math.floor(Math.random() * GLITCH_CHARS.length)]
        : ch,
    )
    .join("");
}

/**
 * Wraps a short piece of nav-link text with a brief hover/focus "glitch"
 * -- a handful of characters flicker to random glyphs for
 * GLITCH_DURATION_MS, then revert to the real text -- per explicit
 * feedback ("I want the links when you hover over them to glitch out a
 * little bit"). `aria-hidden` on the rendered span since the text content
 * changes rapidly and meaninglessly for the animation's duration; the
 * parent link element should carry the real accessible name (e.g. via
 * `aria-label`) so assistive tech never sees the scrambled intermediate
 * states.
 */
export function GlitchText({ children }: { children: string }) {
  const [display, setDisplay] = useState(children);
  const intervalRef = useRef<number | null>(null);
  const reducedMotionRef = useRef(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    reducedMotionRef.current = mq.matches;
    const onChange = () => {
      reducedMotionRef.current = mq.matches;
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // Keep in sync if the prop itself ever changes (e.g. a differently-
  // labeled link reusing this component across a route change).
  useEffect(() => {
    setDisplay(children);
  }, [children]);

  useEffect(() => {
    return () => {
      if (intervalRef.current !== null) clearInterval(intervalRef.current);
    };
  }, []);

  function triggerGlitch() {
    if (reducedMotionRef.current || intervalRef.current !== null) return;
    const start = performance.now();
    intervalRef.current = window.setInterval(() => {
      if (performance.now() - start >= GLITCH_DURATION_MS) {
        if (intervalRef.current !== null) clearInterval(intervalRef.current);
        intervalRef.current = null;
        setDisplay(children);
        return;
      }
      setDisplay(scramble(children));
    }, GLITCH_FRAME_MS);
  }

  return (
    <span aria-hidden="true" onMouseEnter={triggerGlitch} onFocus={triggerGlitch}>
      {display}
    </span>
  );
}
