import { useEffect, useRef, useState } from "react";
import { MatrixRain } from "../../../ascii/MatrixRain";
import { ParticleLayer } from "../../../ascii/ParticleLayer";
import { useBrightnessWave } from "../../layout/useBrightnessWave";
import { usePageMeta } from "../../layout/usePageMeta";
import { GithubRepoCard, LinkChip } from "./GithubRepoCard";
import { ImageCarousel, type CarouselSlide } from "./ImageCarousel";
import { TerminalWindow } from "./TerminalWindow";

// Public base URL for real project-showcase media, uploaded via
// backend/src/logand_backend/scripts/upload_public_asset.py to R2 (see
// docs/secrets.md's STORAGE_BACKEND section) -- unset in production until
// that upload actually happens, in which case every `media()` call below
// returns undefined and CarouselSlide's own "no src" fallback renders a
// labeled placeholder instead of a broken <img>.
//
// For local dev preview, frontend/.env.local (gitignored) sets this to
// "/local-media", matching the gitignored frontend/public/local-media/
// directory -- real files, never committed, see .gitignore's own note.
const MEDIA_BASE_URL = import.meta.env.VITE_MEDIA_BASE_URL;

function media(key: string): string | undefined {
  return MEDIA_BASE_URL ? `${MEDIA_BASE_URL.replace(/\/$/, "")}/${key}` : undefined;
}

interface GithubRef {
  owner: string;
  repo: string;
}

interface Project {
  title: string;
  // One standardized format for every entry: "Mon YYYY", "Mon YYYY - Mon
  // YYYY", or "Mon YYYY - Present" -- no season names (Spring/Fall), so
  // every entry reads on the same scale instead of mixing granularities.
  period: string;
  description: string;
  // Empty (or omitted) skips the carousel panel entirely for this project
  // -- rather than rendering an empty/unlabeled box, which still reserves
  // the same fixed height for nothing.
  slides?: CarouselSlide[];
  // Live-fetched GitHub stats cards (see GithubRepoCard) -- for repos I
  // own/maintain, preferred over a plain link since it's real, current
  // data (stars/language/last-push) rather than a static label.
  githubRepos?: GithubRef[];
  // Anything that isn't a fetchable owned-repo card: a PDF writeup, a
  // YouTube channel, a groupmate-owned repo credit.
  links?: { label: string; href: string }[];
}

// Real project list, newest-first by actual start date -- verified against
// github.com/lognd's real repos (`gh api users/lognd/repos`, real
// created_at/pushed_at timestamps), real EXIF capture dates pulled from
// the original source photos, and dates given directly.
const PROJECTS: Project[] = [
  {
    title: "logand.app",
    period: "Nov 2025 - Present",
    description:
      "This site, and also its own case study: FastAPI + Postgres backend, React/TypeScript frontend, a Rust/WASM ASCII renderer for the animated background you're looking at right now, and a native Android companion app, all in one monorepo. I built it end to end, deploy pipeline included, on purpose: session-cookie auth, Stripe/PayPal invoicing with generated PDF letterheads, a swappable local-disk/Cloudflare-R2 storage layer, and a pre-deploy health-check tool that actually exercises every subsystem instead of trusting that config is correct. GitHub Actions builds and pushes a versioned image to GHCR, runs it through real cross-browser Playwright system tests, and deploys to a Hetzner VPS behind Caddy as a locked-down non-root service account, not root. Public project media lives in its own Cloudflare R2 bucket, synced automatically on every push via a git hook. Real off-box backups, real CI/CD, not a toy deployment.",
    slides: [
      // "/?bg=donut" -- root-relative so this embeds whatever origin the
      // app is actually served from, pinned to one background so the
      // preview looks the same every time rather than a random pick.
      { alt: "logand.app (embedded live)", iframeSrc: "/?bg=donut" },
    ],
  },
  {
    title: "Malmberg: Self-Hosted Photo & Video Wall",
    period: "Jun 2026",
    description:
      "Built for a friend whose photo library had outgrown what cloud storage could hold onto affordably: decades of photos deserve a real home, not a subscription. A low-power Linux/ZFS server holds the actual library; Raspberry Pi displays auto-discover it over LAN, pair with a quick 6-digit PIN, and cross-fade through it with an EXIF-derived, reverse-geocoded overlay. If the server ever drops offline, the displays fall back to a local cache instead of just going blank.",
    slides: [{ alt: "Malmberg display wall" }],
    githubRepos: [{ owner: "lognd", repo: "malmberg" }],
  },
  {
    title: "frob: Agentic Dev Workflow CLI",
    period: "Jun 2026",
    description:
      "I kept watching an AI coding agent burn its context window reading entire files just to change one function, so I built the tool I actually wanted: directory maps with line counts, symbol cross-referencing, token-cost estimation before a file gets read at all, an aggregate quality gate, and an atomic single-symbol edit/commit flow. This whole site was built and maintained with it, day to day.",
    slides: [
      {
        alt: "frob map + frob check, run against this site's own storage module",
        element: (
          <TerminalWindow
            title="frob: backend/src/logand_backend/domain/storage"
            lines={[
              { kind: "prompt", text: "$ frob map backend/src/logand_backend/domain/storage" },
              { kind: "out", text: "backend/src/logand_backend/domain/storage  (5 files, 276 lines)" },
              { kind: "accent", text: "  __init__.py                       1L  ~    1 tok" },
              {
                kind: "accent",
                text: "  base.py                          67L  ~  822 tok  StorageBackend, StorageObjectNotFound",
              },
              { kind: "accent", text: "  factory.py                       37L  ~  438 tok  get_storage_backend" },
              { kind: "accent", text: "  local.py                         68L  ~  699 tok  LocalFilesystemStorage" },
              { kind: "accent", text: "  r2.py                           103L  ~ 1040 tok  CloudflareR2Storage" },
              { kind: "prompt", text: "$ frob check backend/src/logand_backend/domain/storage" },
              {
                kind: "out",
                text: "frob check backend/src/logand_backend/domain/storage  [PASS]  0 errors  0 warnings",
              },
              { kind: "out", text: "  pass  ruff-check              no issues" },
              { kind: "out", text: "  pass  ruff-format             all files formatted" },
              { kind: "out", text: "  pass  frob-cycle              no cycles" },
              { kind: "out", text: "  pass  frob-dup                no duplicates" },
              { kind: "out", text: "  pass  frob-arch               5 suggestions" },
            ]}
          />
        ),
      },
    ],
    githubRepos: [{ owner: "lognd", repo: "frob" }],
  },
  {
    title: "typani: Result/Option/ErrorSet Library",
    period: "Jun 2026",
    description:
      "I kept writing the same Result/Option boilerplate across projects, so I pulled it out into its own library: Rust/Zig-style explicit error handling for Python, Result, Option, and ErrorSet types instead of bare exceptions you have to trace back to find. It's what this site's own FastAPI backend is built on, and it's small enough that adopting it doesn't mean signing up for a whole framework.",
    slides: [
      {
        alt: "A real typani Result/Option session",
        element: (
          <TerminalWindow
            title="python3: typani"
            lines={[
              { kind: "prompt", text: ">>> from typani import Ok, Err, Some, Nothing" },
              { kind: "prompt", text: ">>> divide(10, 2)" },
              { kind: "out", text: "Ok(5.0)" },
              { kind: "prompt", text: ">>> divide(10, 0)" },
              { kind: "out", text: "Err(division by zero)" },
              { kind: "prompt", text: ">>> r1.map(lambda x: x * 2)" },
              { kind: "out", text: "Ok(10.0)" },
              { kind: "prompt", text: ">>> r2.map_err(str.upper)" },
              { kind: "out", text: "Err(DIVISION BY ZERO)" },
              { kind: "prompt", text: ">>> first_positive([-3, -1, 0, 4, 7])" },
              { kind: "out", text: "Some(4)" },
            ]}
          />
        ),
      },
    ],
    githubRepos: [{ owner: "lognd", repo: "typani" }],
  },
  {
    title: "STPONE: Coreless Paper Winder Electronics",
    period: "May 2026",
    description:
      "Built for Swedish Tracing Paper (STP), LLC to replace decades of manual switching and measuring on their coreless paper-winder machine with real electronics: designed the PCB, wrote the ATmega32U4 firmware from the interrupt vectors up, and built a desktop debug application to actually watch what the board was doing over serial instead of guessing from LED blinks. More is in the works.",
    slides: [
      { alt: "STPONE electronics demo", videoSrc: media("stpone-electronics-demo.mp4") },
      { alt: "STPONE PCB design", src: media("stpone-pcb-design.png") },
      { alt: "STPONE electronic schematic", src: media("stpone-electronic-schematic.png") },
      { alt: "STPONE soldering timelapse", videoSrc: media("stpone-soldering-timelapse.mp4") },
    ],
    githubRepos: [{ owner: "lognd", repo: "stpone" }],
  },
  {
    title: "Finite Element Analysis: Torque Arm Optimization",
    period: "Apr 2026",
    description:
      "A structural-optimization project for UF's EML4507 (Finite Element Analysis), built around a question the course itself doesn't hand you: once you have a finite-element model, how do you actually search the design space instead of hand-tuning it? I wrote a gradient-based optimizer that drives ABAQUS directly, finite-difference gradients, a backtracking line search, penalty scheduling for the constraints, and let it run until it converged on a design the 550 MPa allowable stress would actually permit, cutting mass from 2.49kg to 2.13kg.",
    slides: [
      { alt: "Torque arm: Q8-element stress field, final design", src: media("fea2-q8.png") },
      { alt: "Torque arm: mass reduction over the optimization trajectory", src: media("fea2-mass-reduction.jpg") },
    ],
    githubRepos: [{ owner: "lognd", repo: "eml4507-project-2" }],
    links: [
      { label: "Torque arm writeup (PDF)", href: media("fea2-writeup.pdf") ?? "#" },
      { label: "Bike frame writeup (PDF)", href: media("fea1-writeup.pdf") ?? "#" },
    ],
  },
  {
    title: "Design & Manufacture Lab: Air Engine & Food Slicer",
    period: "Oct 2025 - Dec 2025",
    description:
      "Two hands-on design-and-build projects for UF's Design & Manufacture Lab course: a small air engine (machining, welding, assembly, all the way to a running build) and a food slicer, designed and detailed through CAD and formal part/assembly drawings.",
    slides: [
      { alt: "Design & Manufacture Lab team", src: media("air-engine-group-holding-engines.jpg") },
      { alt: "Team welding", src: media("air-engine-group-welding-masks.jpg") },
      { alt: "Food slicer: part drawing", src: media("manufacturing-example-part-drawing.png") },
      { alt: "Food slicer: exploded assembly", src: media("manufacturing-example-exploded-assembly.png") },
      { alt: "Air engine manufacturing demo", videoSrc: media("air-engine-manufacture-demo.mp4") },
    ],
  },
  {
    title: "AIAA: Skipper, LQR Control of a Thrust-Vectored VTOL",
    period: "2025",
    description:
      "As part of the Avionics and GNC team on Florida Rocket Lab (FRL), I co-authored an AIAA paper deriving the full 6-DOF nonlinear equations of motion for Skipper, a mono-propelled VTOL vehicle steered by a 2-DOF gimbaled thrust vector. Linearized the dynamics into a state-space model and designed an LQR controller (solved via the Continuous Algebraic Riccati Equation) with automatic gain scheduling: the controller re-linearizes around a new base point whenever the linear and nonlinear state predictions diverge past tolerance, rather than relying on pre-flight lookup tables. Validated in Simulink against constant crosswind disturbances and 3D reference-tracking.",
    slides: [{ alt: "AIAA student presentation", src: media("aiaa-student-presentation.jpg") }],
    links: [{ label: "Paper (AIAA ARC)", href: "https://arc.aiaa.org/doi/10.2514/6.2025-99754" }],
  },
  {
    title: "Head TA: Advanced Programming Fundamentals",
    period: "Aug 2025 - Present",
    description:
      "As Head TA of UF's Advanced Programming Fundamentals, I authored the exams and nearly all of the course content: 60+ modules, each with around 4 activities and an assignment. Grading that much material by hand doesn't scale, so I also built the tooling behind it. lograder is a Python autograder library built around a composable Input/Check/Mixin/Build/Test pipeline, with Gradescope-compatible scoring. aprog-public holds the public course problem sets I maintain (Python/C++/Jinja).",
    slides: [{ alt: "Selfie with a fellow TA during an exam", src: media("head-ta-selfie.jpg") }],
    githubRepos: [
      { owner: "lognd", repo: "lograder" },
      { owner: "lognd", repo: "aprog-public" },
    ],
  },
  {
    title: "Oops, All Collisions!: Collision-Detection Engine",
    period: "Jul 2025",
    description:
      "A COP3530 (Data Structures & Algorithms) group project built around a real empirical question: which broad-phase collision strategy actually wins, and when? We implemented and benchmarked four: brute-force naive comparison as the baseline, a spatial hash (Minecraft-chunk-style bucketing), a multi-level grid, and sweep-and-prune. I wrote the code solo for the group; the repo lives under a groupmate's account.",
    slides: [
      {
        alt: "Oops, All Collisions! demo (YouTube)",
        embedSrc: "https://www.youtube.com/embed/fO_JSi4XxXk",
      },
    ],
    githubRepos: [{ owner: "elleburkhalter", repo: "Oops-All-Collisions" }],
    links: [{ label: "Demo video (YouTube)", href: "https://www.youtube.com/watch?v=fO_JSi4XxXk" }],
  },
  {
    title: "Mears' Neuroscience Lab: Researcher & ML Model Architect",
    period: "Aug 2024 - Jun 2025",
    description:
      "I ended up in this lab by chance: a conversation on the street about research led to a position applying signal processing and deep learning to rat neurological data. Used the synchro-squeezing transform to sharpen time-frequency structure in raw brainwave recordings, then designed a Longformer-based variational autoencoder to learn a latent space capturing long- and short-term brainwave relationships, trained remotely via SLURM on HiPerGator, UF's supercomputer. My involvement wound down as other commitments picked up, but the modeling work itself stands on its own.",
    githubRepos: [{ owner: "lognd", repo: "bwave" }],
  },
];

// One CreativeWork entry per project, per
// docs/design/10-seo-and-agent-accessibility.md ("Projects page:
// CreativeWork/SoftwareSourceCode entries per project") -- SoftwareSourceCode
// for anything with a real owned repo (a codeRepository an LLM/crawler can
// follow), the plainer CreativeWork otherwise (papers, coursework with no
// repo of its own).
const PROJECTS_JSON_LD = {
  "@context": "https://schema.org",
  "@type": "ItemList",
  itemListElement: PROJECTS.map((project, i) => {
    const primaryRepo = project.githubRepos?.[0];
    return {
      "@type": "ListItem",
      position: i + 1,
      item: {
        "@type": primaryRepo ? "SoftwareSourceCode" : "CreativeWork",
        name: project.title,
        description: project.description,
        temporalCoverage: project.period,
        author: { "@type": "Person", name: "Logan Dapp" },
        ...(primaryRepo
          ? { codeRepository: `https://github.com/${primaryRepo.owner}/${primaryRepo.repo}` }
          : {}),
      },
    };
  }),
};

// Same MatrixRain background + ParticleLayer (mouse-drag/explosion)
// interaction as Landing's "Rain" option, always on here (no picker).
//
// Layout: a vertical snap-scroll feed, one project per "page," genuinely
// scrollable with the scrollbar hidden. See useEffect below for why the
// feed's height is measured in JS rather than left to CSS.
export function Projects() {
  const feedRef = useRef<HTMLDivElement | null>(null);
  useBrightnessWave(feedRef);
  usePageMeta({
    title: "Projects",
    description:
      "Real projects by Logan Dapp: this site's own FastAPI/React/Rust-WASM stack, embedded electronics, finite-element analysis, ML research, and dev tooling like frob and typani.",
    path: "/projects",
  });
  const [feedHeight, setFeedHeight] = useState<number | null>(null);
  useEffect(() => {
    function measure() {
      const el = feedRef.current;
      if (!el) return;
      const top = el.getBoundingClientRect().top;
      setFeedHeight(window.innerHeight - top);
    }
    measure();
    window.addEventListener("resize", measure);
    window.visualViewport?.addEventListener("resize", measure);
    return () => {
      window.removeEventListener("resize", measure);
      window.visualViewport?.removeEventListener("resize", measure);
    };
  }, []);

  return (
    <main className="relative isolate flex flex-1 flex-col">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(PROJECTS_JSON_LD) }}
      />
      <MatrixRain className="absolute inset-0 -z-[5]" />
      <ParticleLayer className="pointer-events-none fixed inset-0 -z-[4]" />
      <div
        ref={feedRef}
        // snap-proximity (not snap-mandatory) -- mandatory forces a hard
        // jump to the nearest snap point on every scroll event, which a
        // mouse wheel's large discrete deltaY-per-notch turns into a
        // violent full-card lurch ("mouse scroll wheel is violent"). A
        // touchpad's small, continuous deltaY events already land near a
        // snap point on their own, so proximity's softer "only snap once
        // you're already close" behavior doesn't change how that feels
        // ("touchpad is very smooth, don't change it") -- it only removes
        // the forced full jump a single hard wheel notch was triggering.
        className="relative z-10 snap-y snap-proximity overflow-y-auto no-scrollbar"
        style={feedHeight != null ? { height: feedHeight } : undefined}
      >
        {PROJECTS.map((project, i) => (
          <section
            key={project.title}
            className={`flex h-full min-h-full shrink-0 snap-start flex-col items-center gap-2 overflow-hidden px-4 ${
              i === 0 ? "py-4" : "py-6"
            }`}
          >
            {i === 0 && (
              <h1 data-wave-text className="shrink-0 text-center text-2xl text-fg-primary">
                Projects
              </h1>
            )}
            <div className="glass-panel flex w-full min-h-0 max-w-2xl flex-1 flex-col overflow-hidden rounded border p-4 sm:p-6">
              {project.slides && project.slides.length > 0 && (
                <div className="shrink-0">
                  <ImageCarousel slides={project.slides} />
                </div>
              )}
              <div className="mt-4 flex shrink-0 flex-wrap items-baseline justify-between gap-x-3">
                <h2 data-wave-text className="text-2xl text-fg-primary">
                  {project.title}
                </h2>
                <span data-wave-text className="text-sm text-fg-muted">
                  {project.period}
                </span>
              </div>
              {/* Description + repo cards + links all live in ONE
                  scrollable region now, not split into a flex-1
                  description fighting a separate shrink-0 row below it --
                  that split let the repo-cards row (which can be 1-2
                  cards tall) claim whatever space it needed first, often
                  squeezing the description down to a sliver ("the
                  description is hidden"). A single scrollable block means
                  the description is always readable top-to-bottom by
                  scrolling, with the repo cards/links simply appearing
                  after it rather than competing for a fixed slice of
                  height. */}
              <div className="mt-2 min-h-[7rem] flex-1 overflow-y-auto no-scrollbar border-y border-border py-2 pr-1">
                <p data-wave-text className="text-base text-fg-primary">
                  {project.description}
                </p>
                {((project.githubRepos && project.githubRepos.length > 0) ||
                  (project.links && project.links.length > 0)) && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {project.githubRepos?.map((r) => (
                      <GithubRepoCard key={`${r.owner}/${r.repo}`} owner={r.owner} repo={r.repo} />
                    ))}
                    {project.links?.map((link) => (
                      <LinkChip key={link.href + link.label} label={link.label} href={link.href} />
                    ))}
                  </div>
                )}
              </div>
            </div>
          </section>
        ))}
      </div>
    </main>
  );
}
