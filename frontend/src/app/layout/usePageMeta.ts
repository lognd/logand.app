import { useEffect } from "react";

const SITE_URL = "https://logand.app";

interface PageMeta {
  title: string;
  description: string;
  // Path only (e.g. "/projects") -- joined with SITE_URL for canonical/OG.
  path: string;
  image?: string;
}

function setMetaTag(attr: "name" | "property", key: string, content: string): void {
  let el = document.querySelector<HTMLMetaElement>(`meta[${attr}="${key}"]`);
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.setAttribute("content", content);
}

function setCanonical(href: string): void {
  let el = document.querySelector<HTMLLinkElement>('link[rel="canonical"]');
  if (!el) {
    el = document.createElement("link");
    el.setAttribute("rel", "canonical");
    document.head.appendChild(el);
  }
  el.setAttribute("href", href);
}

// Client-side-only per-route <title>/description/OG/Twitter/canonical
// updates. This is a stopgap, not the full docs/design/10 story -- real
// crawler/agent visibility needs prerendered HTML (vite-ssg or a build-time
// snapshot step) so a non-JS-executing fetch sees route-specific tags at
// all, not just the index.html defaults. Until that lands, this at least
// gets JS-executing crawlers (Googlebot, most AI agents) and same-origin
// navigation (document.title while browsing) the right per-page metadata,
// and keeps the update logic in one place instead of copy-pasted per page.
export function usePageMeta({ title, description, path, image }: PageMeta): void {
  useEffect(() => {
    const url = `${SITE_URL}${path}`;
    const fullTitle = title === "Logan Dapp" ? title : `${title} | Logan Dapp`;

    document.title = fullTitle;
    setMetaTag("name", "description", description);
    setCanonical(url);

    setMetaTag("property", "og:title", fullTitle);
    setMetaTag("property", "og:description", description);
    setMetaTag("property", "og:url", url);
    setMetaTag("property", "og:type", "website");

    // No site-wide og-image.png exists yet (see index.html's own note) --
    // only set og:image/twitter:image when a caller actually has one,
    // rather than pointing social scrapers at a 404.
    setMetaTag("name", "twitter:card", image ? "summary_large_image" : "summary");
    setMetaTag("name", "twitter:title", fullTitle);
    setMetaTag("name", "twitter:description", description);
    if (image) {
      setMetaTag("property", "og:image", image);
      setMetaTag("name", "twitter:image", image);
    }
  }, [title, description, path, image]);
}
