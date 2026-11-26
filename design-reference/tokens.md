# Sustentra UI Redesign: design tokens

Exact values pulled from the design source files in `source/`. Use these names (or the closest naming the codebase already uses).

## Brand
| Token | Value | Use |
|---|---|---|
| indigo-500 (primary) | #282870 | Primary buttons, active nav, selected states, links |
| indigo-600 (hover) | #1E1E58 | Hover on primary and links |
| indigo-700 (dark) | #282870 | Text on indigo tint, avatar initials |
| indigo-100 (tint) | #E9E9F6 | Soft indigo backgrounds, focus ring |
| indigo-50 | #F4F4FB | Very light indigo surfaces |

Active and selected states always use indigo, never black.

## Neutrals
| Token | Value | Use |
|---|---|---|
| text-primary | #14151A | Headings, main text |
| text-secondary | #3B3D46 | Nav items, body |
| text-muted | #63666F | Secondary lines |
| text-subtle | #6B6E78 | Group labels |
| text-faint | #8A8D96 | Placeholders, hints |
| bg-page | #F3F4F8 | App background |
| bg-surface | #FFFFFF | Cards, panels |
| bg-subtle | #F1F2F6 | Tracks, quiet fills |
| bg-hover | #E9EAF2 | Hover on nav, ghost buttons |
| bg-row-hover | #F7F8FB | Hover on list rows |
| border | #DCDEE6 | Input and card borders |
| border-subtle | #E6E7EC | Dividers |

## Status (one system everywhere)
| Status | Text | Background | Dot / accent |
|---|---|---|---|
| Success / done | #19663E | #E3F5EA | #1F8A55 |
| In progress | #282870 | #E9E9F6 | #282870 |
| Warning / needs attention | #8A4B12 | #FFF1DE | #E9A23B |
| Danger / blocked | #A8281C | #FDE7E4 | #D9473A |
| Neutral / not applicable | #55585F | #F1F2F6 | #8A8D96 |

## Radius
8px (small chips, checkboxes) · 10px (avatars, small buttons) · 11px (buttons, inputs, nav items) · 12px (small cards) · 14px (cards, dropdown panels) · 18px (large cards, modals) · 999px (pills, badges)

## Shadows
| Token | Value |
|---|---|
| card | 0 1px 2px rgba(20,21,26,0.05) |
| card-soft | 0 1px 2px rgba(20,21,26,0.04) |
| primary-button | 0 4px 12px rgba(40,40,112,0.25) |
| primary-button-lg | 0 6px 16px rgba(40,40,112,0.28) |
| focus-ring | 0 0 0 3px #D4D4EC |
| inset-border | inset 0 0 0 1px #DCDEE6 |
| modal / popover | 0 0 0 1px rgba(20,21,26,0.06), 0 24px 48px rgba(20,21,26,0.16) |

## Spacing
Gaps used most: 2, 4, 6, 8, 10, 12, 14px. Card padding 14 to 24px. Sidebar padding 24px 16px 18px.

## Type
- Font stack: `-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'SF Pro Display', Inter, 'Helvetica Neue', Arial, sans-serif`
- Base: 14px, line-height 1.45, `font-variant-numeric: tabular-nums`, `-webkit-font-smoothing: antialiased`
- Sizes: 11 (group labels, badges) · 12 (meta, pills) · 13 (secondary body) · 14 (body) · 15 to 16 (card titles) · 18 to 22 (section titles) · 26 to 30 (page titles, big numbers)
- Weights: 500 (nav, pills) · 600 (titles, labels, most emphasis) · 700 (page titles, big numbers)
- Letter spacing: 0.06em on uppercase group labels, -0.02em on large titles

## Icons
Solid two-tone, 24 viewBox, `fill="currentColor"`, second tone `fill-opacity=".38"`. Default size 18px. Copy paths from the inline SVGs in `source/`. No outline icons inside tinted squares.

## Status pills
Fully round (999px), 6px dot, soft tint background, matching dark text, 12px / 500. Short labels.
