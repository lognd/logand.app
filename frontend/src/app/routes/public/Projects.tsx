import { useRef } from "react";
import { MatrixRain } from "../../../ascii/MatrixRain";
import { ParticleLayer } from "../../../ascii/ParticleLayer";
import { useBrightnessWave } from "../../layout/useBrightnessWave";

// TODO(logan): replace with real project list (CreativeWork/SoftwareSourceCode
// JSON-LD per docs/design/10) once content is provided.
//
// Same MatrixRain background + ParticleLayer (mouse-drag/explosion)
// interaction as Landing's "Rain" option -- per explicit feedback ("I
// actually really like the mouse drag and explosion, can we make that
// appear on the other landing pages?") this isn't picker-selectable here
// (no donut/cube/globe alternative on this page), just always on.
export function Projects() {
  const contentRef = useRef<HTMLDivElement | null>(null);
  useBrightnessWave(contentRef);

  return (
    // No min-h-[480px] floor -- see Landing.tsx's identical fix; it forced
    // overflow whenever the real available height dropped below 480px.
    // flex-1 (not h-full) for the same reason as Landing.tsx's <main> --
    // see Shell.tsx's content-wrapper comment.
    <main className="relative isolate flex flex-1 flex-col">
      <MatrixRain className="absolute inset-0 -z-[5]" />
      <ParticleLayer className="pointer-events-none fixed inset-0 -z-[4]" />
      <div className="relative z-10 flex flex-1 items-center justify-center px-4 py-12">
        {/* ref + data-wave-text: see useBrightnessWave's doc comment. */}
        <div ref={contentRef} className="w-full max-w-2xl">
          <h1 data-wave-text className="mb-4 text-3xl text-fg-primary">
            Projects
          </h1>
          <p data-wave-text className="text-base text-fg-primary">
            A list of projects will appear here.
          </p>
        </div>
      </div>
    </main>
  );
}
