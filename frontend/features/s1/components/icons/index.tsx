/**
 * Sustentra two-tone icon set.
 *
 * Rules:
 *   - Solid filled shapes. viewBox 0 0 24 24, fill="currentColor" so colour comes from parent.
 *   - Main shape at full currentColor; second tone at fillOpacity 0.38.
 *   - Small UI glyphs (chevrons, close, more) are thin-stroke icons.
 *   - Mask icons use useId() so two instances on one page don't clash.
 *   - size defaults to 18. aria-hidden is set when no aria-label is provided.
 *
 * Path data copied exactly from design-reference/source/*.html.
 */
"use client";

import { useId } from "react";
import type { SVGProps } from "react";

export type IconProps = SVGProps<SVGSVGElement> & { size?: number };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function Root({
  size = 18,
  "aria-label": ariaLabel,
  ...rest
}: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden={ariaLabel ? undefined : true}
      aria-label={ariaLabel}
      {...rest}
    />
  );
}

// ---------------------------------------------------------------------------
// Nav icons
// ---------------------------------------------------------------------------

export function IconDashboard(props: IconProps) {
  return (
    <Root {...props}>
      <rect x="3" y="3" width="8" height="8" rx="2.6" fill="currentColor" />
      <rect x="13" y="3" width="8" height="8" rx="2.6" fill="currentColor" fillOpacity=".38" />
      <rect x="3" y="13" width="8" height="8" rx="2.6" fill="currentColor" fillOpacity=".38" />
      <rect x="13" y="13" width="8" height="8" rx="2.6" fill="currentColor" />
    </Root>
  );
}

export function IconSetup(props: IconProps) {
  return (
    <Root {...props}>
      <rect x="3" y="6" width="18" height="2.6" rx="1.3" fill="currentColor" fillOpacity=".38" />
      <rect x="3" y="15.4" width="18" height="2.6" rx="1.3" fill="currentColor" fillOpacity=".38" />
      <circle cx="15.5" cy="7.3" r="3.4" fill="currentColor" />
      <circle cx="8.5" cy="16.7" r="3.4" fill="currentColor" />
    </Root>
  );
}

export function IconUpload(props: IconProps) {
  return (
    <Root {...props}>
      <path
        d="M3 13.5a1.5 1.5 0 0 1 3 0V18h12v-4.5a1.5 1.5 0 0 1 3 0v5A2.5 2.5 0 0 1 18.5 21h-13A2.5 2.5 0 0 1 3 18.5z"
        fill="currentColor"
        fillOpacity=".38"
      />
      <path
        d="M11 3.6a1.4 1.4 0 0 1 2 0l4.2 4.2c.9.9.3 2.2-.9 2.2H14v4.5a2 2 0 0 1-4 0V10H7.7c-1.2 0-1.8-1.3-.9-2.2z"
        fill="currentColor"
      />
    </Root>
  );
}

export function IconEvidence(props: IconProps) {
  const uid = useId();
  const m = `m${uid}`;
  return (
    <Root {...props}>
      <defs>
        <mask id={m} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
          <rect width="24" height="24" fill="#fff" />
          <path
            d="M8.5 13h7M8.5 17h4.5"
            stroke="#000"
            strokeWidth="2.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </mask>
      </defs>
      <g mask={`url(#${m})`}>
        <path
          d="M6.5 2H14v4a2.5 2.5 0 0 0 2.5 2.5H20v11A2.5 2.5 0 0 1 17.5 22h-11A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"
          fill="currentColor"
        />
        <path d="M15.5 2.4L19.6 6.5H16.5a1 1 0 0 1-1-1z" fill="currentColor" fillOpacity=".38" />
      </g>
    </Root>
  );
}

export { IconEvidence as IconDocument };

export function IconCoverage(props: IconProps) {
  return (
    <Root {...props}>
      <path
        d="M6.3 3.5h11.4a2 2 0 0 1 1.9 1.4L21 9.5H3l1.4-4.6a2 2 0 0 1 1.9-1.4z"
        fill="currentColor"
        fillOpacity=".38"
      />
      <path
        d="M2.5 11h5.2a1 1 0 0 1 .9.6l.7 1.4a1 1 0 0 0 .9.6h3.6a1 1 0 0 0 .9-.6l.7-1.4a1 1 0 0 1 .9-.6h5.2v7.5A2.5 2.5 0 0 1 19 21H5a2.5 2.5 0 0 1-2.5-2.5z"
        fill="currentColor"
      />
    </Root>
  );
}

export function IconMethodology(props: IconProps) {
  const uid = useId();
  const m = `m${uid}`;
  return (
    <Root {...props}>
      <defs>
        <mask id={m} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
          <rect width="24" height="24" fill="#fff" />
          <path
            d="M8.5 13.5l2.5 2.5 4.5-5"
            stroke="#000"
            strokeWidth="2.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </mask>
      </defs>
      <g mask={`url(#${m})`}>
        <rect x="4" y="4" width="16" height="18" rx="3" fill="currentColor" />
        <rect x="8" y="2" width="8" height="4.5" rx="1.8" fill="currentColor" fillOpacity=".38" />
      </g>
    </Root>
  );
}

export function IconVerification(props: IconProps) {
  return (
    <Root {...props}>
      <rect x="3.5" y="12" width="4.6" height="9" rx="1.8" fill="currentColor" fillOpacity=".38" />
      <rect x="9.7" y="4" width="4.6" height="17" rx="1.8" fill="currentColor" />
      <rect
        x="15.9"
        y="8.5"
        width="4.6"
        height="12.5"
        rx="1.8"
        fill="currentColor"
        fillOpacity=".38"
      />
    </Root>
  );
}

export function IconOutput(props: IconProps) {
  const uid = useId();
  const m = `m${uid}`;
  return (
    <Root {...props}>
      <defs>
        <mask id={m} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
          <rect width="24" height="24" fill="#fff" />
          <path
            d="M12 11v6M9.5 14.5L12 17l2.5-2.5"
            stroke="#000"
            strokeWidth="2.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </mask>
      </defs>
      <g mask={`url(#${m})`}>
        <path
          d="M6.5 2H14v4a2.5 2.5 0 0 0 2.5 2.5H20v11A2.5 2.5 0 0 1 17.5 22h-11A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"
          fill="currentColor"
        />
        <path d="M15.5 2.4L19.6 6.5H16.5a1 1 0 0 1-1-1z" fill="currentColor" fillOpacity=".38" />
      </g>
    </Root>
  );
}

export function IconActivity(props: IconProps) {
  const uid = useId();
  const m = `m${uid}`;
  return (
    <Root {...props}>
      <defs>
        <mask id={m} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
          <rect width="24" height="24" fill="#fff" />
          <path
            d="M12 7.5V12l3 2"
            stroke="#000"
            strokeWidth="2.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </mask>
      </defs>
      <g mask={`url(#${m})`}>
        <circle cx="12" cy="12" r="9.5" fill="currentColor" />
      </g>
    </Root>
  );
}

export function IconGlossary(props: IconProps) {
  const uid = useId();
  const m = `m${uid}`;
  return (
    <Root {...props}>
      <defs>
        <mask id={m} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
          <rect width="24" height="24" fill="#fff" />
          <path
            d="M9 7.5h6"
            stroke="#000"
            strokeWidth="2.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </mask>
      </defs>
      <g mask={`url(#${m})`}>
        <path
          d="M6.5 2.5H19a1 1 0 0 1 1 1V18H6.5a1.5 1.5 0 0 0 0 3H20v.5a1 1 0 0 1-1 1H6.5A2.5 2.5 0 0 1 4 20V5a2.5 2.5 0 0 1 2.5-2.5z"
          fill="currentColor"
        />
        <rect x="5" y="18" width="15" height="3" rx="1.5" fill="currentColor" fillOpacity=".38" />
      </g>
    </Root>
  );
}

// ---------------------------------------------------------------------------
// UI icons
// ---------------------------------------------------------------------------

export function IconSearch(props: IconProps) {
  return (
    <Root {...props}>
      <path
        fillRule="evenodd"
        fill="currentColor"
        fillOpacity=".38"
        d="M10.5 3a7.5 7.5 0 1 1 0 15 7.5 7.5 0 0 1 0-15zm0 3a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9z"
      />
      <rect
        x="16"
        y="14.2"
        width="3.2"
        height="8"
        rx="1.6"
        transform="rotate(-45 17.6 18.2)"
        fill="currentColor"
      />
    </Root>
  );
}

export function IconMore(props: IconProps) {
  return (
    <Root {...props} fill="currentColor">
      <circle cx="5.5" cy="12" r="1.7" />
      <circle cx="12" cy="12" r="1.7" />
      <circle cx="18.5" cy="12" r="1.7" />
    </Root>
  );
}

export function IconClose(props: IconProps) {
  return (
    <Root {...props} stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M6 6l12 12M18 6L6 18" />
    </Root>
  );
}

export function IconChevronDown(props: IconProps) {
  return (
    <Root
      {...props}
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M6 9l6 6 6-6" />
    </Root>
  );
}

export function IconChevronRight(props: IconProps) {
  return (
    <Root
      {...props}
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M9 6l6 6-6 6" />
    </Root>
  );
}

export function IconChevronLeft(props: IconProps) {
  return (
    <Root
      {...props}
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M15 6l-6 6 6 6" />
    </Root>
  );
}

/** Up/down sort-switch arrows. */
export function IconSwitch(props: IconProps) {
  return (
    <Root
      {...props}
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M8 9l4-4 4 4M8 15l4 4 4-4" />
    </Root>
  );
}

export function IconCheck(props: IconProps) {
  return (
    <Root
      {...props}
      stroke="currentColor"
      strokeWidth="3"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </Root>
  );
}

/** Triangle warning — use for amber / cautionary states. */
export function IconWarning(props: IconProps) {
  const uid = useId();
  const m = `m${uid}`;
  return (
    <Root {...props}>
      <defs>
        <mask id={m} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
          <rect width="24" height="24" fill="#fff" />
          <path
            d="M12 9.5v4"
            stroke="#000"
            strokeWidth="2.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
          <path
            d="M12 17.1v.01"
            stroke="#000"
            strokeWidth="2.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </mask>
      </defs>
      <g mask={`url(#${m})`}>
        <path
          d="M10.2 3.9a2.1 2.1 0 0 1 3.6 0l8 13.8a2.1 2.1 0 0 1-1.8 3.2H4a2.1 2.1 0 0 1-1.8-3.2z"
          fill="currentColor"
        />
      </g>
    </Root>
  );
}

/** Filled circle with info ( i ) — use for neutral explanations. */
export function IconInfo(props: IconProps) {
  const uid = useId();
  const m = `m${uid}`;
  return (
    <Root {...props}>
      <defs>
        <mask id={m} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
          <rect width="24" height="24" fill="#fff" />
          <path
            d="M12 11v5.5"
            stroke="#000"
            strokeWidth="2.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
          <path
            d="M12 7.7v.01"
            stroke="#000"
            strokeWidth="2.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </mask>
      </defs>
      <g mask={`url(#${m})`}>
        <circle cx="12" cy="12" r="10" fill="currentColor" />
      </g>
    </Root>
  );
}

export function IconPlus(props: IconProps) {
  return (
    <Root {...props} stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
      <path d="M12 5v14M5 12h14" />
    </Root>
  );
}

export function IconTrash(props: IconProps) {
  return (
    <Root {...props}>
      <rect x="3.5" y="5" width="17" height="3" rx="1.5" fill="currentColor" fillOpacity=".38" />
      <rect x="9" y="2.5" width="6" height="3.5" rx="1.5" fill="currentColor" fillOpacity=".38" />
      <path
        d="M5.5 9.5h13l-.9 10.2A2.5 2.5 0 0 1 15.1 22H8.9a2.5 2.5 0 0 1-2.5-2.3z"
        fill="currentColor"
      />
    </Root>
  );
}

/** Filled circle with exclamation — use for red / blocking states. */
export function IconAlert(props: IconProps) {
  const uid = useId();
  const m = `m${uid}`;
  return (
    <Root {...props}>
      <defs>
        <mask id={m} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
          <rect width="24" height="24" fill="#fff" />
          <path
            d="M12 7.5v5"
            stroke="#000"
            strokeWidth="2.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
          <path
            d="M12 16.3v.01"
            stroke="#000"
            strokeWidth="2.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </mask>
      </defs>
      <g mask={`url(#${m})`}>
        <circle cx="12" cy="12" r="10" fill="currentColor" />
      </g>
    </Root>
  );
}

// ---------------------------------------------------------------------------
// Content icons
// ---------------------------------------------------------------------------

export function IconBuilding(props: IconProps) {
  const uid = useId();
  const m = `m${uid}`;
  return (
    <Root {...props}>
      <defs>
        <mask id={m} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
          <rect width="24" height="24" fill="#fff" />
          <path
            d="M7 16.5h2M12 16.5h2"
            stroke="#000"
            strokeWidth="2.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </mask>
      </defs>
      <g mask={`url(#${m})`}>
        <path
          d="M3 20.5V10.3a1 1 0 0 1 1.5-.9L9 12V10.3a1 1 0 0 1 1.5-.9L15 12V5a1.5 1.5 0 0 1 1.5-1.5h2A1.5 1.5 0 0 1 20 5v15.5a.5.5 0 0 1-.5.5h-16a.5.5 0 0 1-.5-.5z"
          fill="currentColor"
        />
      </g>
    </Root>
  );
}

export function IconExpandAll(props: IconProps) {
  return (
    <Root
      {...props}
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M8 4l4 4 4-4M8 20l4-4 4 4" />
    </Root>
  );
}

export function IconCollapseAll(props: IconProps) {
  return (
    <Root
      {...props}
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M8 8l4-4 4 4M8 16l4 4 4-4" />
    </Root>
  );
}

export function IconPin(props: IconProps) {
  const uid = useId();
  const m = `m${uid}`;
  return (
    <Root {...props}>
      <defs>
        <mask id={m} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
          <rect width="24" height="24" fill="#fff" />
          <path
            d="M12 9.6v.01"
            stroke="#000"
            strokeWidth="2.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </mask>
      </defs>
      <g mask={`url(#${m})`}>
        <path
          d="M12 2a7.5 7.5 0 0 1 7.5 7.5c0 5.6-6 11.2-6.6 11.8a1.3 1.3 0 0 1-1.8 0C10.5 20.7 4.5 15.1 4.5 9.5A7.5 7.5 0 0 1 12 2z"
          fill="currentColor"
        />
      </g>
    </Root>
  );
}

export function IconCalendar(props: IconProps) {
  const uid = useId();
  const m = `m${uid}`;
  return (
    <Root {...props}>
      <defs>
        <mask id={m} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
          <rect width="24" height="24" fill="#fff" />
          <path
            d="M7.5 14.5h.01M12 14.5h.01M16.5 14.5h.01M7.5 17.8h.01M12 17.8h.01"
            stroke="#000"
            strokeWidth="2.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </mask>
      </defs>
      <g mask={`url(#${m})`}>
        <rect x="3" y="4.5" width="18" height="5" rx="2.5" fill="currentColor" fillOpacity=".38" />
        <path
          d="M3 10.5h18v8A2.5 2.5 0 0 1 18.5 21h-13A2.5 2.5 0 0 1 3 18.5z"
          fill="currentColor"
        />
        <rect x="7" y="2.5" width="2.6" height="5" rx="1.3" fill="currentColor" />
        <rect x="14.4" y="2.5" width="2.6" height="5" rx="1.3" fill="currentColor" />
      </g>
    </Root>
  );
}

export function IconLock(props: IconProps) {
  const uid = useId();
  const m = `m${uid}`;
  return (
    <Root {...props}>
      <defs>
        <mask id={m} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
          <rect width="24" height="24" fill="#fff" />
          <path
            d="M12 14.5v2.5"
            stroke="#000"
            strokeWidth="2.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </mask>
      </defs>
      <g mask={`url(#${m})`}>
        <path
          d="M7.5 10V8a4.5 4.5 0 0 1 9 0v2h-2.6V8a1.9 1.9 0 0 0-3.8 0v2z"
          fill="currentColor"
          fillOpacity=".38"
        />
        <rect x="4.5" y="10" width="15" height="11.5" rx="3" fill="currentColor" />
      </g>
    </Root>
  );
}

/** Chat bubble — the Ask Sustentra assistant icon. */
export function IconSparkle(props: IconProps) {
  const uid = useId();
  const m = `m${uid}`;
  return (
    <Root {...props}>
      <defs>
        <mask id={m} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
          <rect width="24" height="24" fill="#fff" />
          <path
            d="M8.5 9.5h7M8.5 12.5h4.5"
            stroke="#000"
            strokeWidth="2.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </mask>
      </defs>
      <g mask={`url(#${m})`}>
        <path
          d="M12 3c5 0 9 3.4 9 7.7s-4 7.7-9 7.7c-1 0-2-.1-2.9-.4L4.6 20c-.7.3-1.4-.4-1.1-1.1l1.2-3C3.6 14.4 3 12.6 3 10.7 3 6.4 7 3 12 3z"
          fill="currentColor"
        />
      </g>
    </Root>
  );
}

/** Paper-plane send icon. */
export function IconSend(props: IconProps) {
  const uid = useId();
  const m = `m${uid}`;
  return (
    <Root {...props}>
      <defs>
        <mask id={m} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
          <rect width="24" height="24" fill="#fff" />
          <path
            d="M10.6 13.4L16 8"
            stroke="#000"
            strokeWidth="2.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </mask>
      </defs>
      <g mask={`url(#${m})`}>
        <path
          d="M20.6 2.4c.9-.3 1.4.4 1.1 1.2l-6.4 17.2c-.4 1-1.7 1-2.1.1l-2.6-6-6-2.6c-.9-.4-.9-1.7.1-2.1z"
          fill="currentColor"
        />
      </g>
    </Root>
  );
}

export function IconCopy(props: IconProps) {
  return (
    <Root
      {...props}
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="8" y="8" width="12" height="12" rx="2" />
      <path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3" />
    </Root>
  );
}

export function IconThumbUp(props: IconProps) {
  return (
    <Root
      {...props}
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M7 11v9H4v-9zM7 11l4-7a2 2 0 0 1 3 2l-1 4h5.5a2 2 0 0 1 2 2.4l-1.3 6A2 2 0 0 1 17.2 20H7" />
    </Root>
  );
}

/** Same shape as IconThumbUp, rotated 180°. */
export function IconThumbDown(props: IconProps) {
  return (
    <Root
      {...props}
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <g transform="rotate(180 12 12)">
        <path d="M7 11v9H4v-9zM7 11l4-7a2 2 0 0 1 3 2l-1 4h5.5a2 2 0 0 1 2 2.4l-1.3 6A2 2 0 0 1 17.2 20H7" />
      </g>
    </Root>
  );
}

/** Download arrow — tray base + down arrow. */
export function IconDownload(props: IconProps) {
  return (
    <Root {...props}>
      <path
        d="M3 13.5a1.5 1.5 0 0 1 3 0V18h12v-4.5a1.5 1.5 0 0 1 3 0v5A2.5 2.5 0 0 1 18.5 21h-13A2.5 2.5 0 0 1 3 18.5z"
        fill="currentColor"
        fillOpacity=".38"
      />
      <path
        d="M13 15.4a1.4 1.4 0 0 1-2 0l-4.2-4.2c-.9-.9-.3-2.2.9-2.2H10V4.5a2 2 0 0 1 4 0V9h2.3c1.2 0 1.8 1.3.9 2.2z"
        fill="currentColor"
      />
    </Root>
  );
}

/** Tag / label icon — used for document type classification. */
export function IconTag(props: IconProps) {
  const uid = useId();
  const m = `m${uid}`;
  return (
    <Root {...props}>
      <defs>
        <mask id={m} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
          <rect width="24" height="24" fill="#fff" />
          <path
            d="M7.6 7.6v.01"
            stroke="#000"
            strokeWidth="2.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </mask>
      </defs>
      <g mask={`url(#${m})`}>
        <path
          d="M3 4.5A1.5 1.5 0 0 1 4.5 3h7a1.5 1.5 0 0 1 1 .4l8.1 8.1a1.5 1.5 0 0 1 0 2.1l-7 7a1.5 1.5 0 0 1-2.1 0L3.4 12.5a1.5 1.5 0 0 1-.4-1z"
          fill="currentColor"
        />
      </g>
    </Root>
  );
}

/** Document note with folded corner. */
export function IconNote(props: IconProps) {
  const uid = useId();
  const m = `m${uid}`;
  return (
    <Root {...props}>
      <defs>
        <mask id={m} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
          <rect width="24" height="24" fill="#fff" />
          <path
            d="M7.5 8h9M7.5 11.5h5"
            stroke="#000"
            strokeWidth="2.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </mask>
      </defs>
      <g mask={`url(#${m})`}>
        <path
          d="M5.5 3h13A2.5 2.5 0 0 1 21 5.5V14h-4.5a2.5 2.5 0 0 0-2.5 2.5V21H5.5A2.5 2.5 0 0 1 3 18.5v-13A2.5 2.5 0 0 1 5.5 3z"
          fill="currentColor"
        />
        <path d="M15.5 15.5H21L15.5 21z" fill="currentColor" fillOpacity=".38" />
      </g>
    </Root>
  );
}

/** Filled circle with checkmark — resolved / success states. */
export function IconCheckCircle(props: IconProps) {
  const uid = useId();
  const m = `m${uid}`;
  return (
    <Root {...props}>
      <defs>
        <mask id={m} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
          <rect width="24" height="24" fill="#fff" />
          <path
            d="M7.8 12.3l2.8 2.8 5.6-5.8"
            stroke="#000"
            strokeWidth="2.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </mask>
      </defs>
      <g mask={`url(#${m})`}>
        <circle cx="12" cy="12" r="10" fill="currentColor" />
      </g>
    </Root>
  );
}

/** Lightning bolt — AI document recognition. */
export function IconFlash(props: IconProps) {
  return (
    <Root {...props}>
      <path
        d="M13.5 2.3c.5-.6 1.4-.2 1.3.6L14 9.5h5c.8 0 1.2.9.7 1.5l-9.2 10.7c-.5.6-1.4.2-1.3-.6L10 14.5H5c-.8 0-1.2-.9-.7-1.5z"
        fill="currentColor"
      />
    </Root>
  );
}

/** Cloud with upload arrow — file drop zone. */
export function IconCloudUpload(props: IconProps) {
  return (
    <Root {...props}>
      <path
        d="M7 19a5 5 0 0 1-.8-9.9A6.5 6.5 0 0 1 18.6 8.6 4.6 4.6 0 0 1 17.5 19z"
        fill="currentColor"
        fillOpacity=".38"
      />
      <path
        d="M12.9 10.3l3 3c.6.6.2 1.7-.7 1.7H13.3v4a1.3 1.3 0 0 1-2.6 0v-4H8.8c-.9 0-1.3-1.1-.7-1.7l3-3a1.3 1.3 0 0 1 1.8 0z"
        fill="currentColor"
      />
    </Root>
  );
}

export function IconArrowRight(props: IconProps) {
  return (
    <Root
      {...props}
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M5 12h14M13 6l6 6-6 6" />
    </Root>
  );
}

/** Rotate-and-retry arrow. */
export function IconRetry(props: IconProps) {
  return (
    <Root
      {...props}
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M20 12a8 8 0 1 1-2.4-5.7L20 8.5M20 4v4.5h-4.5" />
    </Root>
  );
}

/** 5-pointed star — used to flag AI-read values. */
export function IconStar(props: IconProps) {
  return (
    <Root {...props}>
      <path
        d="M11.1 2.9a1 1 0 0 1 1.8 0l2.4 4.9 5.4.8a1 1 0 0 1 .6 1.7l-3.9 3.8.9 5.4a1 1 0 0 1-1.5 1L12 18l-4.8 2.5a1 1 0 0 1-1.5-1l.9-5.4-3.9-3.8a1 1 0 0 1 .6-1.7l5.4-.8z"
        fill="currentColor"
      />
    </Root>
  );
}

/** Two-row checklist with square bullets — coverage task list. */
export function IconChecklist(props: IconProps) {
  return (
    <Root {...props}>
      <rect x="10" y="5.5" width="11" height="3" rx="1.5" fill="currentColor" fillOpacity=".38" />
      <rect x="10" y="15.5" width="11" height="3" rx="1.5" fill="currentColor" fillOpacity=".38" />
      <rect x="2.5" y="3" width="6" height="6" rx="2" fill="currentColor" />
      <rect x="2.5" y="14" width="6" height="6" rx="2" fill="currentColor" />
    </Root>
  );
}

/** Compose / new-chat icon (rectangle + pen). */
export function IconCompose(props: IconProps) {
  return (
    <Root
      {...props}
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 5H6a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-6" />
      <path d="M16.5 3.5l4 4L12 16H8v-4z" />
    </Root>
  );
}

/** Up-arrow submit — the chat send button. */
export function IconSendUp(props: IconProps) {
  return (
    <Root
      {...props}
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 19V5M6 11l6-6 6 6" />
    </Root>
  );
}

/** Horizontal top bar + two-column body — data-point review split view. */
export function IconLayoutSplit(props: IconProps) {
  return (
    <Root {...props}>
      <rect x="3" y="3.5" width="18" height="5" rx="2" fill="currentColor" fillOpacity=".38" />
      <path
        d="M3 10h5.5v11H5.5A2.5 2.5 0 0 1 3 18.5zM10 10h11v8.5a2.5 2.5 0 0 1-2.5 2.5H10z"
        fill="currentColor"
      />
    </Root>
  );
}

/** Envelope — used on the verify-email / OTP screen. */
export function IconMail({ size = 18, ...props }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden={props["aria-label"] ? undefined : true}
      {...props}
    >
      <defs>
        <mask id="icon-mail-mask" maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
          <rect width="24" height="24" fill="#fff" />
          <path
            d="M6 8.5l6 4.2 6-4.2"
            stroke="#000"
            strokeWidth="2.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </mask>
      </defs>
      <g mask="url(#icon-mail-mask)">
        <rect x="2.5" y="4.5" width="19" height="15" rx="3" fill="currentColor" />
      </g>
    </svg>
  );
}

/** Pen / highlight edit tool — document annotation. */
export function IconHighlighter(props: IconProps) {
  return (
    <Root
      {...props}
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M9 11l-5 5v4h4l5-5M12.5 7.5l4 4L20 8l-4-4z" />
    </Root>
  );
}
