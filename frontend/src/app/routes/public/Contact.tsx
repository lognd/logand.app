import { MatrixRain } from "../../../ascii/MatrixRain";
import { ParticleLayer } from "../../../ascii/ParticleLayer";

// TODO(logan): fill in real ContactPoint details (see docs/design/10 JSON-LD spec).
//
// Same MatrixRain background + ParticleLayer interaction as Landing's
// "Rain" option -- see Projects.tsx for why this is unconditional here
// rather than picker-selectable.
export function Contact() {
  return (
    // No min-h-[480px] floor -- see Landing.tsx's identical fix; it forced
    // overflow whenever the real available height dropped below 480px.
    // flex-1 (not h-full) for the same reason as Landing.tsx's <main> --
    // see Shell.tsx's content-wrapper comment.
    <main className="relative isolate flex flex-1 flex-col">
      <MatrixRain className="absolute inset-0 -z-[5]" />
      <ParticleLayer className="pointer-events-none fixed inset-0 -z-[4]" />
      <div className="relative z-10 flex flex-1 items-center justify-center px-4 py-12">
        <div className="w-full max-w-2xl">
          <h1 className="mb-4 text-3xl text-fg-primary">Contact</h1>
          <p className="text-base text-fg-primary">Contact details will appear here.</p>
        </div>
      </div>
    </main>
  );
}
