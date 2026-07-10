import { useEffect } from "react";

// FINDINGS L3: the single-use verify/claim token rides in the page URL and
// leaks to any cross-origin subresource via the `Referer` header before the
// route scrubs it. Emitting <meta name="referrer" content="no-referrer">
// while such a route is mounted suppresses that header entirely, closing the
// window. There is no head-management library in this app (see
// usePageMeta.ts), so this sets the tag imperatively and removes it on
// unmount so it never affects any other route.
export function useNoReferrer(): void {
  useEffect(() => {
    const existing = document.querySelector<HTMLMetaElement>(
      'meta[name="referrer"]',
    );
    if (existing) {
      // Some other owner already set a referrer policy -- leave it be.
      return;
    }
    const el = document.createElement("meta");
    el.setAttribute("name", "referrer");
    el.setAttribute("content", "no-referrer");
    document.head.appendChild(el);
    return () => {
      el.remove();
    };
  }, []);
}
