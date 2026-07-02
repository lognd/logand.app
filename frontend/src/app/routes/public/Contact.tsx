import { useRef } from "react";
import { MatrixRain } from "../../../ascii/MatrixRain";
import { ParticleLayer } from "../../../ascii/ParticleLayer";
import { useBrightnessWave } from "../../layout/useBrightnessWave";
import { usePageMeta } from "../../layout/usePageMeta";
import {
  EmailIcon,
  GithubIcon,
  InstagramIcon,
  LinkedinIcon,
  PhoneIcon,
  YoutubeIcon,
} from "./Icons";

interface ContactEntry {
  label: string;
  value: string;
  href: string;
  note?: string;
  icon: (props: { className?: string }) => React.JSX.Element;
  // Each entry gets its own accent color (from the site's 4-color
  // Gruvbox accent set) so the page reads as more than one flat block of
  // text -- "there's a single color for everything... which makes it
  // look boring." Repeats are fine (there are only 4 accents for 7
  // entries); the icon shape is doing most of the differentiation work.
  accent: string;
}

// Real contact channels -- phone/Instagram/LinkedIn/YouTube/email/GitHub,
// as given directly by the user. Phone and LinkedIn each carry an
// explicit caveat (spam filtering, stale profile) rather than presenting
// them as equally-reliable as the others.
const CONTACT_ENTRIES: ContactEntry[] = [
  {
    label: "Email",
    value: "logan@logand.app",
    href: "mailto:logan@logand.app",
    icon: EmailIcon,
    accent: "text-accent-aqua",
  },
  {
    label: "Email (alt)",
    value: "logan@logandapp.com",
    href: "mailto:logan@logandapp.com",
    icon: EmailIcon,
    accent: "text-accent-aqua",
  },
  {
    label: "Phone",
    value: "+1 (423) 779-2811",
    href: "tel:+14237792811",
    note: "Strict spam filtering: unfamiliar numbers may not get through. Email is more reliable.",
    icon: PhoneIcon,
    accent: "text-accent-orange",
  },
  {
    label: "GitHub",
    value: "github.com/lognd",
    href: "https://github.com/lognd",
    icon: GithubIcon,
    accent: "text-accent-green",
  },
  {
    label: "Instagram",
    value: "@logan.dapp",
    href: "https://instagram.com/logan.dapp",
    icon: InstagramIcon,
    accent: "text-accent-red",
  },
  {
    label: "YouTube",
    value: "@logandapp7542",
    href: "https://www.youtube.com/@logandapp7542",
    icon: YoutubeIcon,
    accent: "text-accent-red",
  },
  {
    label: "LinkedIn",
    value: "linkedin.com/in/logandapp",
    href: "https://www.linkedin.com/in/logandapp",
    note: "Not actively kept up to date: GitHub and email are better places to reach me.",
    icon: LinkedinIcon,
    accent: "text-accent-aqua",
  },
];

// Same MatrixRain background + ParticleLayer interaction as Landing's
// "Rain" option -- see Projects.tsx for why this is unconditional here
// rather than picker-selectable.
// Person schema with an embedded ContactPoint, per
// docs/design/10-seo-and-agent-accessibility.md ("Contact: ContactPoint
// embedded in the Person schema, not a separate page-level schema") --
// mirrors Landing.tsx's PERSON_JSON_LD rather than duplicating a second
// Person entity, with the real channels from CONTACT_ENTRIES above.
const CONTACT_PERSON_JSON_LD = {
  "@context": "https://schema.org",
  "@type": "Person",
  name: "Logan Dapp",
  url: "https://logand.app",
  jobTitle: "Software, Embedded, and Mechanical Engineer",
  sameAs: [
    "https://github.com/lognd",
    "https://www.youtube.com/@logandapp7542",
    "https://instagram.com/logan.dapp",
    "https://www.linkedin.com/in/logandapp",
  ],
  contactPoint: {
    "@type": "ContactPoint",
    email: "logan@logand.app",
    telephone: "+1-423-779-2811",
    contactType: "personal",
  },
};

export function Contact() {
  const contentRef = useRef<HTMLDivElement | null>(null);
  useBrightnessWave(contentRef);
  usePageMeta({
    title: "Contact",
    description:
      "Get in touch with Logan Dapp -- email, GitHub, LinkedIn, Instagram, YouTube, and phone.",
    path: "/contact",
  });

  return (
    // No min-h-[480px] floor -- see Landing.tsx's identical fix; it forced
    // overflow whenever the real available height dropped below 480px.
    // flex-1 (not h-full) for the same reason as Landing.tsx's <main> --
    // see Shell.tsx's content-wrapper comment.
    <main className="relative isolate flex flex-1 flex-col">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(CONTACT_PERSON_JSON_LD) }}
      />
      <MatrixRain className="absolute inset-0 -z-[5]" />
      <ParticleLayer className="pointer-events-none fixed inset-0 -z-[4]" />
      <div className="relative z-10 flex flex-1 items-center justify-center overflow-y-auto px-4 py-12">
        {/* ref + data-wave-text: see useBrightnessWave's doc comment.
            glass-panel -- same translucent bordered treatment as the
            Projects page's cards, instead of contact details floating
            directly over the animated background. */}
        <div ref={contentRef} className="glass-panel w-full max-w-3xl rounded border p-4 sm:p-6">
          <h1 data-wave-text className="mb-4 text-3xl text-fg-primary">
            Contact
          </h1>
          {/* A 2-column grid of compact cards, not a long single-column
              list of thin, border-separated rows ("a lot of short
              sections which make it ugly to look at") -- each card holds
              its own icon/label/value/note together as one unit instead
              of stacking many short strips end to end. */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {CONTACT_ENTRIES.map((entry) => {
              const Icon = entry.icon;
              return (
                <a
                  key={entry.label}
                  href={entry.href}
                  target={entry.href.startsWith("http") ? "_blank" : undefined}
                  rel={entry.href.startsWith("http") ? "noreferrer" : undefined}
                  className="flex min-h-11 items-start gap-3 rounded border border-border px-3 py-3 no-underline transition-colors hover:border-accent-aqua focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-orange"
                >
                  <Icon className={`h-6 w-6 shrink-0 ${entry.accent}`} />
                  <div className="min-w-0">
                    <div data-wave-text className="text-xs uppercase tracking-wide text-fg-muted">
                      {entry.label}
                    </div>
                    <div data-wave-text className="truncate text-base text-fg-primary">
                      {entry.value}
                    </div>
                    {entry.note && (
                      <p data-wave-text className="mt-1 text-xs text-fg-secondary">
                        {entry.note}
                      </p>
                    )}
                  </div>
                </a>
              );
            })}
          </div>
        </div>
      </div>
    </main>
  );
}
