import { useEffect, useState } from "react";
import { CHIP_LINK_CLASS } from "../../../styles/a11y";
import { DocumentIcon, GithubIcon } from "./Icons";
import { SkeletonLine, Throbber } from "./Throbber";

interface RepoData {
  description: string | null;
  pushed_at: string;
}

// GitHub's own repo object only reports one "dominant language" field --
// the real per-language breakdown lives at a separate endpoint (byte
// counts per language, GitHub's own linguist analysis), which is what
// "don't just have dominant language; put all the languages used" needs.
type LanguagesData = Record<string, number>;

function formatLanguages(languages: LanguagesData): string {
  const names = Object.entries(languages)
    .sort(([, a], [, b]) => b - a)
    .map(([name]) => name);
  return names.length > 0 ? names.join(", ") : "multi-language";
}

// GitHub blocks embedding github.com itself in an <iframe> (it sends
// X-Frame-Options: deny on every page), so a literal iframe embed of a
// repo just renders blank -- there's no way around that from our side.
// This is the real alternative: a live, client-side fetch against
// api.github.com (a plain CORS-enabled JSON GET, no auth needed for
// public repo data) rendered as a small stats card, so what's shown is
// actually fetched from GitHub at page-load time rather than typed in by
// hand and left to go stale.
export function GithubRepoCard({ owner, repo }: { owner: string; repo: string }) {
  const [data, setData] = useState<RepoData | null>(null);
  const [languages, setLanguages] = useState<LanguagesData | null>(null);
  const [failed, setFailed] = useState(false);
  const href = `https://github.com/${owner}/${repo}`;

  useEffect(() => {
    let cancelled = false;
    // On a fast connection this fetch can resolve in well under 100ms --
    // fast enough that the loading skeleton flashes for a frame or two
    // and is easy to miss entirely ("the skeleton throbber doesn't show
    // up"). Padding the resolve with a minimum delay (via Promise.all,
    // not a fixed sleep before the fetch even starts) keeps the loading
    // state on screen long enough to actually register as "loading,"
    // without slowing down a genuinely slow fetch any further.
    const minDelay = new Promise((resolve) => setTimeout(resolve, 400));
    Promise.all([
      fetch(`https://api.github.com/repos/${owner}/${repo}`).then((res) =>
        res.ok ? res.json() : Promise.reject(new Error(String(res.status))),
      ),
      // A separate real endpoint, not derived from the repo object's own
      // single `language` field -- see LanguagesData's doc comment.
      fetch(`https://api.github.com/repos/${owner}/${repo}/languages`).then((res) =>
        res.ok ? res.json() : ({} as LanguagesData),
      ),
      minDelay,
    ])
      .then(([json, langs]: [RepoData, LanguagesData, unknown]) => {
        if (!cancelled) {
          setData(json);
          setLanguages(langs);
        }
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [owner, repo]);

  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="flex min-w-0 flex-1 flex-col rounded border border-border bg-bg-secondary px-3 py-2 no-underline transition-colors hover:border-accent-aqua"
    >
      <div className="flex items-center gap-2">
        <GithubIcon className="h-4 w-4 shrink-0 text-accent-green" />
        <span className="truncate font-mono text-sm text-fg-primary">
          {owner}/{repo}
        </span>
        {!data && !failed && <Throbber className="ml-auto h-3.5 w-3.5 shrink-0" />}
      </div>
      {data ? (
        <>
          {data.description && (
            <p className="mt-1 truncate text-sm text-fg-secondary">{data.description}</p>
          )}
          <p className="mt-1 truncate text-xs text-fg-muted">
            {formatLanguages(languages ?? {})}: updated{" "}
            {new Date(data.pushed_at).toLocaleDateString("en-US", {
              year: "numeric",
              month: "short",
            })}
          </p>
        </>
      ) : failed ? (
        <p className="mt-1 text-sm text-fg-muted">View on GitHub</p>
      ) : (
        <div className="mt-1.5 flex flex-col gap-1.5">
          <SkeletonLine className="h-3.5 w-4/5" />
          <SkeletonLine className="h-3 w-2/5" />
        </div>
      )}
    </a>
  );
}

// Same treatment, but for a link that isn't a fetchable GitHub repo card
// (a PDF, a YouTube channel, a groupmate-owned repo credit) -- kept here
// so Projects.tsx has one consistent "chip" import for every non-embedded
// reference link.
export function LinkChip({ label, href }: { label: string; href: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={`${CHIP_LINK_CLASS} min-w-0 flex-1 justify-center`}
    >
      <DocumentIcon className="h-4 w-4 shrink-0 text-accent-orange" />
      <span className="truncate">{label}</span>
    </a>
  );
}
