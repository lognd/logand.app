import { MatrixRain } from "../../../ascii/MatrixRain";

// TODO(logan): fill in real ContactPoint details (see docs/design/10 JSON-LD spec).
//
// Same MatrixRain background + mouse-drag/explosion interaction as
// Landing's "Rain" option -- see Projects.tsx for why this is unconditional
// here rather than picker-selectable.
export function Contact() {
  return (
    <main className="relative isolate h-full min-h-[480px]">
      <MatrixRain className="absolute inset-0 -z-[5]" />
      <div className="relative mx-auto w-full max-w-2xl px-4 py-12">
        <h1 className="mb-4 text-3xl text-fg-primary">Contact</h1>
        <p className="text-base text-fg-primary">Contact details will appear here.</p>
      </div>
    </main>
  );
}
