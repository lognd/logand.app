// Small, generic (not brand-accurate logo reproductions) monochrome-path
// icons, colored via `className` (currentColor) -- addresses "there's a
// single color for everything... maybe it's because there are no
// symbols," giving each contact/link type its own recognizable shape
// instead of relying on color alone to distinguish them.
type IconProps = { className?: string };

function IconBase({ className, children }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      {children}
    </svg>
  );
}

export function EmailIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M3 7l9 6 9-6" />
    </IconBase>
  );
}

export function PhoneIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z" />
    </IconBase>
  );
}

export function GithubIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <circle cx="12" cy="8" r="5" />
      <circle cx="6" cy="18" r="2.5" />
      <circle cx="18" cy="18" r="2.5" />
      <path d="M12 13v2M9.5 16l-1.5 1M14.5 16l1.5 1" />
    </IconBase>
  );
}

export function InstagramIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <rect x="3" y="3" width="18" height="18" rx="5" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="17" cy="7" r="0.8" fill="currentColor" stroke="none" />
    </IconBase>
  );
}

export function LinkedinIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="8" cy="9" r="0.9" fill="currentColor" stroke="none" />
      <path d="M8 12v6M13 18v-4a2 2 0 0 1 4 0v4M13 12v6" />
    </IconBase>
  );
}

export function YoutubeIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <rect x="2.5" y="5" width="19" height="14" rx="4" />
      <path d="M10.5 9.5l5 2.5-5 2.5z" fill="currentColor" stroke="none" />
    </IconBase>
  );
}

export function DocumentIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M7 3h7l4 4v14H7z" />
      <path d="M14 3v4h4" />
      <path d="M9.5 13h5M9.5 16h5" />
    </IconBase>
  );
}
