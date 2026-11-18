# ShopFlow design system

Generated with the `ui-ux-pro-max` skill, then corrected for retail POS use
(the skill's default serif pairing was an academia style — wrong for a
cashier screen). Master file + tokens live in `design-system/shopflow/`.

## Palette (emerald retail)

| Token | Value | Use |
|---|---|---|
| `--color-primary` | `#15803D` | Brand, primary CTAs, active nav |
| `--color-primary-strong` | `#166534` | Hover/active states |
| `--color-primary-soft` | `#22C55E` | Secondary accents |
| `--color-primary-050/100/200` | `#F0FDF4/#DCFCE7/#BBF7D0` | Surfaces, fills |
| `--color-accent` | `#0369A1` | Links, info |
| `--color-destructive` | `#DC2626` | Errors, expiry ≤ 30d |
| `--color-amber` | `#D97706` | Warnings, low stock |
| `--color-surface` | `#F0FDF4` | App background |
| `--color-card` | `#FFFFFF` | Cards, tables |
| `--color-muted(-fg)` | `#E8F0F1` / `#475569` | Muted surfaces/text |
| `--color-border` | `#BBF7D0` | Borders |
| `--color-ink` | `#14532D` | Body text |

## Type

- **Sans**: Plus Jakarta Sans (`--font-sans`) — the skill's "Friendly SaaS" pick
- **Bangla**: Noto Sans Bengali (`--font-bengali`), extra line-height 1.75 on `[lang=bn]`
- Figures always Latin digits for POS legibility; `tabular-nums` on money
- Scale: 12 meta · 14 label · 15–16 body · 18 section · 22–24 title · 30 KPI

## Interaction (skill priorities)

1. **a11y**: 4.5:1 contrast, `:focus-visible` ring, `aria-label` on icon buttons,
   `prefers-reduced-motion` respected
2. **touch**: ≥ 44×44 px targets, `min-h-[44px]`/52 px primary CTAs, 8 px gaps
3. **mobile-first**: bottom nav ≤ 5 items < 1024 px, sidebar ≥ 1024 px,
   `pb-28` clears the nav, no horizontal page scroll (`.table-scroll` wraps tables)
4. **charts**: Recharts area chart, emerald fill, axis + tooltip, `role="img"`
   + `aria-label` (colour is never the only signal — values shown)

## Component notes

Cards `rounded-xl` with 1 px border + `shadow-[0_1px_2px]` — flat per the
skill's Flat Design pick. `Badge` variants for status (success/warning/danger/
outline). `KpiCard`, `EmptyState`, `Skeleton`/`KpiSkeleton` cover the three
states (data / loading / empty).

## Verified breakpoints

375 · 768 · 1024 · 1440 — see `docs/screenshots/`.
