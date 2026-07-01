import { useEffect, useRef, useState } from "react";

// Printable ASCII "glitch" glyphs -- not letters/digits, so a substituted
// character always reads as visibly "wrong" rather than accidentally
// spelling a different real word.
const GLITCH_CHARS = "!<>-_\\/[]{}=+*^?#&$~";
// Slowed down from an earlier 400ms/40ms ("make the glitch out a little
// slower") -- longer overall duration and a slower per-frame flicker rate,
// so each substituted character has time to actually register before the
// next swap instead of reading as a blur.
const GLITCH_DURATION_MS = 650;
const GLITCH_FRAME_MS = 70;
// Exactly one or two characters substituted per frame, never a
// proportional fraction of the whole word -- "the glitching should be
// like one or two characters" (a fraction-based rate looked like "a lot"
// on longer words, which is what "should be a lot more subtle" was
// about).
const MIN_SUBSTITUTIONS = 1;
const MAX_SUBSTITUTIONS = 2;

function scramble(text: string): string {
  const chars = [...text];
  const eligibleIndices = chars.map((_ch, i) => i).filter((i) => chars[i] !== " ");
  const count = Math.min(
    eligibleIndices.length,
    MIN_SUBSTITUTIONS + Math.round(Math.random() * (MAX_SUBSTITUTIONS - MIN_SUBSTITUTIONS)),
  );
  // Fisher-Yates-ish partial shuffle -- picks `count` distinct positions
  // without ever substituting the same character twice in one frame.
  for (let i = eligibleIndices.length - 1; i > eligibleIndices.length - 1 - count; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [eligibleIndices[i], eligibleIndices[j]] = [eligibleIndices[j], eligibleIndices[i]];
    chars[eligibleIndices[i]] = GLITCH_CHARS[Math.floor(Math.random() * GLITCH_CHARS.length)];
  }
  return chars.join("");
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
