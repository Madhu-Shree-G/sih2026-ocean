/**
 * Inline SVG marks and ornament.
 *
 * Everything here is drawn rather than loaded so the app has no external asset
 * dependency - it renders identically on a venue machine with no network.
 * These are simplified, stylised devices for an interface mock, not exact
 * reproductions of official insignia.
 */

interface MarkProps {
  className?: string;
}

/** Stylised national emblem device used as the application mark. */
export function Emblem({ className }: MarkProps) {
  return (
    <svg
      className={className}
      viewBox="0 0 40 50"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      role="img"
      aria-label="National emblem"
    >
      {/* Lion capital silhouette */}
      <path d="M12 13c0-3.2 3.4-5.6 8-5.6s8 2.4 8 5.6c0 2.3-1.4 3.6-2.6 4.4H14.6C13.4 16.6 12 15.3 12 13Z" />
      <path d="M16.4 7.6c.7-2 1.9-3.2 3.6-3.2s2.9 1.2 3.6 3.2" />
      <circle cx="16.8" cy="12" r="1" fill="currentColor" stroke="none" />
      <circle cx="23.2" cy="12" r="1" fill="currentColor" stroke="none" />

      {/* Abacus */}
      <path d="M11 17.8h18v3.4H11z" />
      {/* Dharma wheel */}
      <circle cx="20" cy="19.5" r="2.9" />
      <path d="M20 16.6v5.8M17.1 19.5h5.8M17.9 17.4l4.2 4.2M22.1 17.4l-4.2 4.2" strokeWidth="0.85" />

      {/* Bell-shaped lotus base */}
      <path d="M13.4 21.4c-.5 3.4-2.1 5.6-4.4 6.8h22c-2.3-1.2-3.9-3.4-4.4-6.8" />
      <path d="M9 28.2h22" />

      {/* Satyameva Jayate scroll */}
      <path d="M10.6 31.6h18.8" strokeWidth="1" />
      <path d="M13 34.9h14M15 38.2h10M16.6 41.5h6.8" strokeWidth="0.9" opacity="0.75" />
    </svg>
  );
}

/** INCOIS roundel: a compass rose over concentric rings. */
export function IncoisMark({ className }: MarkProps) {
  return (
    <svg
      className={className}
      viewBox="0 0 44 44"
      role="img"
      aria-label="INCOIS"
    >
      <defs>
        <radialGradient id="incoisFill" cx="42%" cy="34%" r="72%">
          <stop offset="0%" stopColor="#1c4f7a" />
          <stop offset="62%" stopColor="#0e2f4d" />
          <stop offset="100%" stopColor="#071c30" />
        </radialGradient>
      </defs>

      <circle cx="22" cy="22" r="21" fill="url(#incoisFill)" stroke="#2a6b9e" strokeWidth="1.2" />
      <circle cx="22" cy="22" r="16.5" fill="none" stroke="#3d8dc4" strokeWidth="0.7" opacity="0.55" />

      {/* Compass rose */}
      <path d="M22 6.5 24.4 19.6 22 22 19.6 19.6Z" fill="#7fd4ff" opacity="0.95" />
      <path d="M22 37.5 19.6 24.4 22 22 24.4 24.4Z" fill="#3f97cc" opacity="0.9" />
      <path d="M6.5 22 19.6 19.6 22 22 19.6 24.4Z" fill="#3f97cc" opacity="0.9" />
      <path d="M37.5 22 24.4 24.4 22 22 24.4 19.6Z" fill="#7fd4ff" opacity="0.95" />

      {/* Wave motif */}
      <path
        d="M9 29.5c2.6-1.9 5.2-1.9 7.8 0s5.2 1.9 7.8 0 5.2-1.9 7.8 0"
        fill="none"
        stroke="#8fe3ff"
        strokeWidth="1.35"
        strokeLinecap="round"
        opacity="0.8"
      />
      <circle cx="22" cy="22" r="2.1" fill="#0a1420" stroke="#8fe3ff" strokeWidth="1" />
    </svg>
  );
}

/**
 * Decorative monument skyline anchoring the base of the layers rail.
 * Purely ornamental; hidden from assistive technology.
 */
export function MonumentSkyline({ className }: MarkProps) {
  return (
    <svg
      className={className}
      viewBox="0 0 300 110"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.05"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {/* --- Left: stepped temple gopuram --- */}
      <path d="M6 96V70l7-6 7 6v26" />
      <path d="M8.5 70h9M9.5 64h7M11 58.5h4.5M13.2 58.5v-4" />
      <path d="M10 76h6M10 82h6M10 88h6" opacity="0.55" />

      {/* --- Qutub-style minaret --- */}
      <path d="M30 96V52c0-1.6 1.1-2.6 2.6-2.6s2.6 1 2.6 2.6v44" />
      <path d="M29 62h7.2M29.4 72h6.4M30 82h5.2" opacity="0.6" />
      <path d="M32.6 49.4v-4.6M31 44.8h3.2" />

      {/* --- Centre-left: Taj Mahal --- */}
      <path d="M52 96V74h44v22" />
      <path d="M60 74V62M88 74V62" opacity="0.6" />
      {/* main dome */}
      <path d="M62 62c0-8.8 5.4-15.5 12-15.5S86 53.2 86 62" />
      <path d="M74 46.5v-5M72.2 41.5h3.6M74 38.5v-3" />
      {/* side domes */}
      <path d="M56.5 74c0-4.4 2.2-7.6 5-7.6s5 3.2 5 7.6" opacity="0.75" />
      <path d="M81.5 74c0-4.4 2.2-7.6 5-7.6s5 3.2 5 7.6" opacity="0.75" />
      {/* arch */}
      <path d="M69 96V82c0-3 2.2-5.2 5-5.2s5 2.2 5 5.2v14" />
      {/* minarets */}
      <path d="M46 96V58M50 96V58M98 96V58M102 96V58" opacity="0.8" />
      <path d="M45 58h6M97 58h6" />
      <path d="M48 58v-5M100 58v-5" />

      {/* --- India Gate --- */}
      <path d="M116 96V70c0-5.6 4-9.6 9.5-9.6s9.5 4 9.5 9.6v26" />
      <path d="M113 70h25M113 64h25" opacity="0.55" />
      <path d="M122 96V82c0-2.2 1.6-3.8 3.5-3.8s3.5 1.6 3.5 3.8v14" opacity="0.7" />

      {/* --- Charminar --- */}
      <path d="M150 96V72h34v24" />
      <path d="M148 72h38" />
      <path d="M154 72V58M180 72V58" opacity="0.6" />
      <path d="M152 58h5.5M177 58h5.5" />
      <path d="M154.8 58v-6M179.8 58v-6" />
      <path d="M160 96V80c0-3.6 2.8-6.4 7-6.4s7 2.8 7 6.4v16" />
      <path d="M163 68c0-2.6 1.8-4.5 4-4.5s4 1.9 4 4.5" opacity="0.7" />

      {/* --- Konark wheel --- */}
      <circle cx="206" cy="80" r="13" opacity="0.85" />
      <circle cx="206" cy="80" r="4.4" opacity="0.7" />
      <g opacity="0.55">
        <path d="M206 67v26M193 80h26M197 71l18 18M215 71l-18 18" />
      </g>
      <path d="M188 96h36" />

      {/* --- Lotus temple --- */}
      <path d="M236 96c0-9 4.4-15.5 9.6-15.5S255 87 255 96" />
      <path d="M244 96c0-11 4.6-19 10-19s10 8 10 19" />
      <path d="M254 96c0-9 4.4-15.5 9.6-15.5S273 87 273 96" opacity="0.8" />
      <path d="M232 96h45" />

      {/* --- Right: stupa --- */}
      <path d="M282 96c0-7.6 3.6-13 8-13s8 5.4 8 13" />
      <path d="M290 83v-5M287.6 78h4.8" />
      <path d="M279 96h22" />

      {/* --- Ground / wave line --- */}
      <path
        d="M0 101c14-4.5 28-4.5 42 0s28 4.5 42 0 28-4.5 42 0 28 4.5 42 0 28-4.5 42 0 28 4.5 42 0 28-4.5 42 0"
        strokeWidth="1.3"
        opacity="0.75"
      />
      <path
        d="M0 107c14-3.6 28-3.6 42 0s28 3.6 42 0 28-3.6 42 0 28 3.6 42 0 28-3.6 42 0 28 3.6 42 0 28-3.6 42 0"
        strokeWidth="0.9"
        opacity="0.4"
      />
    </svg>
  );
}
