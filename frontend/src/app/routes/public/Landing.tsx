// Public routes must render real semantic content -- crawlers and the
// vite-ssg prerender pass (see docs/design/10) read this markup directly,
// not a post-hydration DOM. Keep real text here even at stub stage.
export function Landing() {
  return (
    <main>
      <h1>Logan Dapp</h1>
      <p>
        Personal and professional site of Logan Dapp -- software engineer,
        builder of logand.app.
      </p>
      <nav aria-label="primary">
        <a href="/projects">Projects</a>
        <a href="/contact">Contact</a>
      </nav>
    </main>
  );
}
