/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_USE_MOCKS?: string;
  // Public base URL for project-showcase media (photos/videos/PDFs)
  // uploaded via backend/src/logand_backend/scripts/upload_public_asset.py --
  // see Projects.tsx's `media()` helper. Unset means those slides render
  // as labeled placeholders instead of a broken <img>, same fallback
  // convention as CarouselSlide's own optional `src`.
  readonly VITE_MEDIA_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
