import type { ShapeKind } from "./shapes";

export type BackgroundOption = ShapeKind | "rain";

const OPTIONS: { value: BackgroundOption; label: string }[] = [
  { value: "donut", label: "Donut" },
  { value: "cube", label: "Cube" },
  { value: "sphere", label: "Globe" },
  { value: "rain", label: "Rain" },
];

// Mutually-exclusive background selector (exactly one of donut/cube/globe/
// rain is ever showing at once) -- replaces an earlier design where matrix
// rain was a separately-toggled overlay on top of whichever shape happened
// to be showing; the user explicitly asked for "EITHER show the cube OR
// the donut OR the globe OR the matrix rain", i.e. one selection among
// peers, not an independent on/off layered over the others.
//
// Implemented as a `radiogroup` of real buttons rather than native
// <input type="radio"> -- gives full control over styling without fighting
// native radio appearance, while keeping the same selection semantics for
// assistive tech via role="radio"/aria-checked.
//
// Deliberately understated, not styled like BUTTON_CLASS's normal
// high-contrast bordered buttons: per feedback this should live in the
// footer and be "kind of hidden" -- a quiet row of small text labels, not
// a prominent control competing with the real page content. Still keeps a
// real 44x44px hit area (the padding) and a visible focus ring for
// keyboard/screen-reader users even though the resting visual weight is
// low, per docs/design/09's accessibility bar -- "subtle" applies to
// idle-state styling, not to the tap target size or focus visibility.
export function BackgroundPicker({
  value,
  onChange,
  className,
}: {
  value: BackgroundOption;
  onChange: (next: BackgroundOption) => void;
  className?: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Background animation"
      className={`flex flex-wrap gap-1 ${className ?? ""}`}
    >
      {OPTIONS.map((opt) => {
        const selected = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(opt.value)}
            className={`min-h-11 min-w-11 rounded px-3 py-2 text-sm text-fg-muted
              transition-opacity focus-visible:outline focus-visible:outline-2
              focus-visible:outline-offset-2 focus-visible:outline-accent-orange ${
                selected ? "opacity-100" : "opacity-40 hover:opacity-80"
              }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
