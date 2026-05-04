# RoutePass — Design System

> Source of truth for all visual and UX decisions. Every frontend component must be built against this document. Update it when decisions change — never drift silently.

---

## Brand Concept

**RoutePass** sits at the intersection of outdoor sport and productivity tooling. The visual language must feel:

- **Trustworthy** — handling athletes' personal activity data and API credentials
- **Purposeful** — a tool, not a toy; every pixel earns its place
- **Outdoor-grounded** — nature as texture, not decoration (no fake gradients or stock photo forests)
- **Modern SaaS** — clean enough to sit beside Linear, Supabase, or Vercel in a browser tab

Tone: calm confidence. Not aggressive (Strava's orange energy). Not corporate (Garmin's grey). Not playful (Wahoo's neons).

---

## Color Palette

> **Design pivot (Session 5):** RoutePass switched to a **dark-first** design system inspired by Vercel and n8n. The defaults in `globals.css` and `tailwind.config.ts` are now dark. Light mode is available as an opt-in `.light` class but is not the shipped default. The source of truth is `globals.css` — `DESIGN.md` mirrors it.

### Core Tokens (dark default)

| Token | Value | Usage |
|-------|-------|-------|
| `--color-primary` | `#3ECFAF` | Primary buttons, active nav, key CTAs (mint on dark) |
| `--color-primary-hover` | `#2EB89A` | Hover state for primary actions |
| `--color-primary-light` | `rgba(62,207,175,0.1)` | Subtle primary tint (selected rows, focus rings) |
| `--color-accent` | `#3ECFAF` | Same as primary on dark — highlights, badges |
| `--color-accent-hover` | `#2EB89A` | Hover on accent elements |
| `--color-bg` | `#0a0a0a` | App background |
| `--color-surface` | `#111111` | Cards, modals, panels |
| `--color-surface-raised` | `#171717` | Secondary surfaces, table rows |
| `--color-border` | `#242424` | Default borders |
| `--color-border-strong` | `#303030` | Dividers, focused inputs |
| `--color-text-primary` | `#ededed` | Body copy, headings |
| `--color-text-secondary` | `#737373` | Captions, helper text, labels |
| `--color-text-disabled` | `#525252` | Disabled states |
| `--color-text-inverse` | `#0a0a0a` | Text on mint/light surfaces |

### Semantic Tokens (dark-tuned)

| Token | Value | Usage |
|-------|-------|-------|
| `--color-success` | `#34d399` | Sync complete, connected status |
| `--color-success-light` | `rgba(52,211,153,0.12)` | Success alert backgrounds |
| `--color-warning` | `#fbbf24` | Rate limit warnings, quota alerts |
| `--color-warning-light` | `rgba(251,191,36,0.12)` | Warning alert backgrounds |
| `--color-error` | `#f87171` | Errors, disconnected/failed states |
| `--color-error-light` | `rgba(248,113,113,0.12)` | Error alert backgrounds |
| `--color-info` | `#60a5fa` | Informational notes |
| `--color-info-light` | `rgba(96,165,250,0.12)` | Info alert backgrounds |

### Light Mode Override (`.light` class)

Applied via the `.light` CSS class — not the default. Forest green becomes the primary on light.

| Token | Value |
|-------|-------|
| `--color-primary` | `#16533A` |
| `--color-primary-hover` | `#124430` |
| `--color-primary-light` | `#E8F5F0` |
| `--color-bg` | `#F5F7F5` |
| `--color-surface` | `#FFFFFF` |
| `--color-surface-raised` | `#FAFAFA` |
| `--color-border` | `#E2E8E4` |
| `--color-border-strong` | `#C8D4CE` |
| `--color-text-primary` | `#111827` |

---

## Typography

### Typefaces

| Role | Family | Source |
|------|--------|--------|
| UI / headings / body | **Inter** | Google Fonts (`next/font`) |
| Monospace (API keys, code) | **JetBrains Mono** | Google Fonts (`next/font`) |

No system font stacks — load both at app boot via `next/font/google`. Inter covers Latin + common extended scripts. JetBrains Mono for all API key displays, JSON previews, and code snippets.

### Type Scale

| Name | Size | Line height | Weight | Tag |
|------|------|------------|--------|-----|
| `display` | 36px | 1.2 | 700 | `h1` (landing only) |
| `heading-xl` | 30px | 1.25 | 700 | `h1` (dashboard) |
| `heading-lg` | 24px | 1.3 | 600 | `h2` |
| `heading-md` | 20px | 1.35 | 600 | `h3` |
| `heading-sm` | 16px | 1.4 | 600 | `h4`, card titles |
| `body-lg` | 16px | 1.6 | 400 | Intro paragraphs |
| `body` | 14px | 1.6 | 400 | Default body copy |
| `body-sm` | 13px | 1.5 | 400 | Secondary info, table rows |
| `caption` | 12px | 1.4 | 400 | Timestamps, helper text |
| `label` | 12px | 1.0 | 500 | Form labels, badges |
| `mono` | 13px | 1.5 | 400 | API keys, IDs |

### Usage Rules

- Maximum line width (prose): 65ch
- Never use font weights below 400 in the app
- Form labels: always `label` size + weight 500 + `--color-text-secondary`
- Never uppercase body copy; uppercase allowed for `label` in nav and badges only

---

## Spacing System

Base unit: **4px**. All spacing is a multiple of 4.

| Token | px | Usage |
|-------|----|-------|
| `space-1` | 4px | Icon gap, tight inline spacing |
| `space-2` | 8px | Input padding, button icon gap |
| `space-3` | 12px | Card padding (compact), list item gap |
| `space-4` | 16px | Default padding, form field gap |
| `space-5` | 20px | Section internal padding |
| `space-6` | 24px | Card padding (standard) |
| `space-8` | 32px | Section gap inside a page |
| `space-10` | 40px | Section gap between major blocks |
| `space-12` | 48px | Page top padding |
| `space-16` | 64px | Hero/landing large gap |

---

## Border Radius

| Token | px | Usage |
|-------|----|-------|
| `radius-sm` | 4px | Inputs (internal), tooltips |
| `radius-md` | 8px | Buttons, inputs (border), badges |
| `radius-lg` | 12px | Cards, modals, dropdowns |
| `radius-xl` | 16px | Large panels, feature cards |
| `radius-full` | 9999px | Pills, status dots, avatar circles |

---

## Shadows / Elevation

| Token | Value | Usage |
|-------|-------|-------|
| `shadow-sm` | `0 1px 2px rgba(0,0,0,0.06)` | Buttons, inputs on hover |
| `shadow-md` | `0 4px 12px rgba(0,0,0,0.08)` | Cards, dropdowns |
| `shadow-lg` | `0 8px 24px rgba(0,0,0,0.10)` | Modals, popovers |
| `shadow-inner` | `inset 0 2px 4px rgba(0,0,0,0.04)` | Active/pressed inputs |

---

## Iconography

### UI Icons

Library: **Lucide React** (`lucide-react`). No other icon library for UI chrome.

- Default icon size: `16px` (inline) / `20px` (standalone in buttons) / `24px` (navigation)
- Stroke width: `1.5px` default (Lucide default) — do not change globally
- Color: always inherit from text color (`currentColor`) unless explicitly semantic

| Concept | Icon |
|---------|------|
| Sync / Refresh | `RefreshCw` |
| Pipelines | `GitMerge` |
| Success / connected | `CheckCircle2` |
| Error / disconnected | `XCircle` |
| Warning | `AlertTriangle` |
| Settings | `Settings2` |
| API key | `Key` |
| Rules | `Filter` |
| Billing | `CreditCard` |
| Logout | `LogOut` |

### Platform Brand Icons

Every platform (and RoutePass itself) has a dedicated SVG icon set under `public/icons/`:

```
public/icons/
├── Regular/    ← full-colour brand icons (use on dark surfaces)
├── White/      ← white monochrome (use on coloured or dark backgrounds)
└── Black/      ← black monochrome (use on light backgrounds)
```

**Never render a platform using a Lucide icon.** Always use the brand SVG.

#### Icon components (`components/platform-icons.tsx`, `components/brand-box.tsx`)

| Component | Purpose |
|-----------|---------|
| `<BrandIcon brand="strava" variant="regular" size={24} />` | Bare SVG icon, sized |
| `<BrandBox brand="komoot" size={40} />` | Icon in a tinted square container (icon = 58% of box) |
| `<BrandBadge brand="intervals_icu" variant="ghost" />` | Clickable badge — ghost / outline / filled |
| `<PlatformIcon platform="garmin" size={20} />` | Alias for `BrandIcon` (legacy API) |
| `<RoutePassIcon size={24} />` | RoutePass icon specifically |

`variant="inactive"` renders the white icon at 30% opacity — use for disconnected/coming-soon states.

#### Brand registry (`lib/brand-registry.ts`)

Single source of truth for all brand metadata. Every entry has:

```ts
{
  id: string
  name: string          // display name, e.g. "Garmin Connect"
  url: string           // canonical URL for badge links
  colors: { primary }   // hex — used for tint backgrounds and hover states
  assets: {
    regular: string     // path under /public
    white: string
    black: string
  }
}
```

#### Supported platforms

| Key | Name | Primary colour |
|-----|------|---------------|
| `routepass` | RoutePass | `#3ECFAF` |
| `strava` | Strava | `#FC4C02` |
| `komoot` | Komoot | `#6AA127` |
| `garmin` | Garmin Connect | `#2eace2` |
| `polar` | Polar Flow | `#C8173D` |
| `wahoo` | Wahoo | `#A3A3A3` |
| `suunto` | Suunto | `#e1001a` |
| `intervals_icu` | Intervals.icu | `#dd0447` |
| `runalyze` | Runalyze | `#7dbe63` |
| `trainingpeaks` | TrainingPeaks | `#3074f8` |
| `webhook` | Webhook | `#c93762` |
| `local` | Local | `#4F46E5` |

### App Icon

**File:** `frontend/app/icon.svg`

Two abstract mountain silhouettes (forest green `#16533a`) occupy the lower half of a square canvas. A bold mint route line (`#3ecfaf`) originates from a filled circle at bottom-left, arcs upward through the mountain pass, and terminates in an arrowhead at top-right. Dark-mode adaptation: mountains switch to white via `@media (prefers-color-scheme: dark)`; the mint route line is always mint.

---

## Component Specifications

### Button

Three variants, two sizes.

**Variant: Primary**
- Background: `--color-primary`
- Text: `--color-text-inverse`
- Hover: `--color-primary-hover`
- Border-radius: `radius-md`
- Height: 36px (sm) / 40px (md, default)
- Padding: 0 16px (sm) / 0 20px (md)
- Font: body-sm / body, weight 500
- Focus ring: 2px offset, `--color-accent`

**Variant: Secondary**
- Background: `--color-surface`
- Border: 1px solid `--color-border-strong`
- Text: `--color-text-primary`
- Hover: `--color-surface-raised` background

**Variant: Ghost**
- Background: transparent
- Text: `--color-text-secondary`
- Hover: `--color-primary-light` background, `--color-primary` text

**Variant: Danger**
- Same as Primary but `--color-error` background

**Disabled state** (all): 50% opacity, `cursor-not-allowed`, no hover effect.

### Input / Textarea

- Height: 36px (text input)
- Border: 1px solid `--color-border`
- Border-radius: `radius-md`
- Padding: 0 12px
- Background: `--color-surface`
- Focus: border `--color-accent`, `shadow-inner`, no outline (custom focus only)
- Error: border `--color-error`, error message below in `caption` + `--color-error`
- Helper text: `caption` + `--color-text-secondary`, 4px below input

### Card

- Background: `--color-surface`
- Border: 1px solid `--color-border`
- Border-radius: `radius-lg`
- Padding: 24px
- Shadow: `shadow-md`
- No hover state by default (only if the whole card is clickable)
- Card header: heading-sm + optional right-side action button
- Card section separator: 1px solid `--color-border`, 16px vertical margin

### Badge / Status Pill

- Border-radius: `radius-full`
- Padding: 2px 8px
- Font: `label` size, weight 500
- Height: 20px

| State | Background | Text |
|-------|-----------|------|
| Connected | `--color-success-light` | `--color-success` |
| Syncing | `--color-info-light` | `--color-info` |
| Error | `--color-error-light` | `--color-error` |
| Paused | `--color-warning-light` | `--color-warning` |
| Free tier | `--color-bg` | `--color-text-secondary` |
| Pro | `--color-primary-light` | `--color-primary` |

### Alert / Toast

- Border-left: 3px solid (semantic color)
- Background: semantic light variant
- Border-radius: `radius-md`
- Padding: 12px 16px
- Icon: 16px, left-aligned, semantic color
- Title: `body-sm` weight 600
- Body: `body-sm` weight 400

### Table

- Header: `label` font, `--color-text-secondary`, `--color-surface-raised` background
- Row height: 48px
- Row hover: `--color-primary-light` background
- Border: 1px solid `--color-border` on bottom of each row
- Pagination: Ghost buttons + `caption` page indicator

### Form

- Label above input, gap: 6px
- Field gap (vertical between fields): 16px
- Required marker: `*` in `--color-error`, after label text
- Section header within a form: `heading-sm` + 32px top margin

---

## Layout & Navigation

### App Shell

```
┌─────────────────────────────────────────────────┐
│  Topbar (60px) — logo + user menu + notifications│
├──────────────┬──────────────────────────────────┤
│  Sidebar     │  Main content area               │
│  (240px)     │  max-width: 1024px, centered     │
│              │  padding: 32px                   │
│              │                                  │
└──────────────┴──────────────────────────────────┘
```

- Sidebar collapses to icon-only (64px) on medium screens
- Mobile: sidebar becomes bottom navigation (4 primary items)
- Content max-width: 1024px (centered, not full-bleed — feels focused, not sprawling)

### Sidebar Navigation Items

```
▸ Dashboard
▸ Activities
▸ Sync
▸ Connections    (Komoot, Strava, Intervals, etc.)
▸ Rules          (Pro badge if free tier)
▸ API Keys       (Pro badge if free tier)
─────────────
▸ Billing
▸ Settings
▸ Docs (external link)
```

### Topbar

- Left: RoutePass wordmark (logo SVG + "RoutePass" in heading-sm, primary color)
- Right: sync status indicator dot + notification bell + avatar/user menu
- Height: 60px, `--color-surface` background, 1px border-bottom `--color-border`

---

## Page Templates

### Dashboard

```
[Sync status card — full width]
  Current status: Active / Paused / Error
  Last synced: relative time + activity name
  [Sync now] button

[2-column grid]
  [Activities card]          [Connections card]
  Last 5 activities list     Platform connection chips
  [View all →]               [Manage →]

[Usage card — full width, free tier only]
  Daily Strava budget bar
  "Upgrade to Pro" CTA
```

### Activities List

- Search input + date range filter + direction filter
- Table: activity name | type icon | date | platform | status badge | [GPX download]
- Pagination: 25 per page

### Connections Page

One card per platform. Card states:
- **Not connected**: muted border, "Connect" primary button
- **Connected**: green chip, last-sync info, "Disconnect" ghost/danger button
- **Error**: red chip, error message, "Reconnect" button

### Settings

Tabbed: Profile | Sync Preferences | Notifications | Danger Zone

---

## Motion & Transitions

- Default transition: `150ms ease-out`
- Page transitions: none (instant) — avoid perceived lag on navigation
- Modal enter: `200ms ease-out`, scale 0.97→1 + opacity 0→1
- Toast: slide in from right `200ms ease-out`, auto-dismiss 4s
- Sync indicator pulse: 2s infinite CSS `pulse` animation on the status dot
- Loading skeleton: `shimmer` keyframes, 1.5s ease-in-out

---

## Frontend Stack & Tooling

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Framework | Next.js 14+ App Router | SSR for landing page SEO; RSC for dashboard data |
| Styling | Tailwind CSS v3 | Utility-first; token values map to Tailwind config |
| Component primitives | shadcn/ui (Radix) | Accessible, unstyled base; we apply RoutePass tokens |
| Icons | Lucide React | Consistent, tree-shakeable |
| Charts | Recharts | Activity history, quota usage charts |
| Forms | React Hook Form + Zod | Type-safe validation; matches backend Pydantic schemas |
| API client | TanStack Query v5 | Cache, invalidation, optimistic updates |
| Auth state | zustand (minimal) | JWT token storage + user session |
| Fonts | `next/font/google` — Inter + JetBrains Mono | Zero layout shift |

---

## Frontend Implementation Plan

### Step 1 — Design Token Wiring (Day 1)

- Create `tailwind.config.ts` extending default theme with RoutePass tokens
- Map every CSS variable above to a Tailwind utility (`primary`, `accent`, `surface`, etc.)
- Create `globals.css` with CSS custom properties for the full color + radius + shadow set
- Set up `next/font` for Inter + JetBrains Mono, attach to `html` element
- **Deliverable**: `npm run dev` shows a blank page with correct background color and font

### Step 2 — Base Component Library (Days 1–2)

Build in `components/ui/` using shadcn/ui as primitive base:
- `Button` (all variants + sizes + loading state)
- `Input`, `Textarea`, `Label`, `FormField` (with error state)
- `Card`, `CardHeader`, `CardContent`, `CardFooter`
- `Badge`, `StatusDot`
- `Alert` (4 semantic variants)
- `Skeleton` (shimmer loading)
- `Dialog` / `Modal`
- `Dropdown` / `Select`
- `Table`, `TableRow`, `TablePagination`
- `Tooltip`

Each component: TypeScript, no hardcoded colors (always from token), Storybook story optional.

### Step 3 — App Shell (Day 2)

- `components/layout/Topbar.tsx`
- `components/layout/Sidebar.tsx` (collapsible)
- `components/layout/MobileNav.tsx`
- `app/(dashboard)/layout.tsx` — wraps all authenticated pages with shell
- `app/(auth)/layout.tsx` — minimal centered layout for login/register

### Step 4 — Auth Pages (Day 3)

- `/login` — email + password form, redirect to dashboard
- `/register` — email + password + confirm, auto-login
- `/forgot-password` (stub — "email sent" state only for now)
- Auth state: JWT stored in `httpOnly` cookie via Next.js route handler → no XSS exposure

### Step 5 — Dashboard & Activities (Days 3–4)

- `/dashboard` — sync status, last activities, connections overview, quota bar
- `/activities` — paginated table + filters + GPX download
- `/activities/[id]` — detail view (map placeholder + activity metadata)

### Step 6 — Connections Page (Day 4–5)

- `/connections` — one card per platform
- Komoot: form (email + password), POST `/auth/komoot/connect`
- Strava: OAuth redirect button → `/auth/strava/connect`
- Intervals.icu: API key + athlete ID form (Phase 6 backend)
- Runalyze: personal token form (Phase 6 backend)
- Polar: OAuth button (Phase 7 backend)
- Outdooractive: OAuth button (Phase 7 backend)
- Platforms not yet in backend: show "Coming soon" chip

### Step 7 — Settings & Billing (Day 5)

- `/settings` — profile + sync prefs + notifications
- `/billing` — current plan + usage + Stripe Checkout button + portal link
- `/api-keys` — list + create + revoke (Pro only, with upgrade CTA for free tier)
- `/rules` — rule list + create/edit drawer (Pro only)

### Step 8 — Landing Page (separate from dashboard, Day 6)

- Single-page marketing: hero, feature list, pricing (free/pro), FAQ, footer
- Topbar: logo + nav links + "Sign up" primary CTA
- Hero: tagline + sub-text + [Get started free] + [See how it works] (scrolls to features)
- Pricing: two cards (Free / Pro), annual toggle, Stripe checkout link
- Dark/light: landing page can use a darker hero (primary color background) for visual punch

---

## File Structure (Frontend)

```
/frontend
├── app/
│   ├── (auth)/
│   │   ├── login/page.tsx
│   │   └── register/page.tsx
│   ├── (dashboard)/
│   │   ├── layout.tsx            ← app shell
│   │   ├── dashboard/page.tsx
│   │   ├── activities/
│   │   │   ├── page.tsx
│   │   │   └── [id]/page.tsx
│   │   ├── connections/page.tsx
│   │   ├── rules/page.tsx
│   │   ├── api-keys/page.tsx
│   │   ├── settings/page.tsx
│   │   └── billing/page.tsx
│   ├── (landing)/
│   │   └── page.tsx              ← marketing landing page
│   ├── globals.css
│   └── layout.tsx                ← root layout, fonts, providers
├── components/
│   ├── ui/                       ← base design system components
│   │   ├── button.tsx
│   │   ├── input.tsx
│   │   ├── card.tsx
│   │   ├── badge.tsx
│   │   ├── alert.tsx
│   │   ├── skeleton.tsx
│   │   ├── dialog.tsx
│   │   ├── dropdown.tsx
│   │   ├── table.tsx
│   │   └── tooltip.tsx
│   ├── layout/
│   │   ├── topbar.tsx
│   │   ├── sidebar.tsx
│   │   └── mobile-nav.tsx
│   ├── connections/
│   │   ├── connection-card.tsx   ← reusable for each platform
│   │   └── platform-icons.tsx
│   ├── activities/
│   │   ├── activity-table.tsx
│   │   └── activity-row.tsx
│   └── sync/
│       ├── sync-status-card.tsx
│       └── sync-now-button.tsx
├── lib/
│   ├── api.ts                    ← TanStack Query + fetch wrapper
│   ├── auth.ts                   ← JWT cookie helpers
│   └── utils.ts                  ← cn(), date formatting, sport type labels
├── hooks/
│   ├── use-user.ts
│   ├── use-activities.ts
│   └── use-connections.ts
├── store/
│   └── auth.ts                   ← zustand auth slice
├── tailwind.config.ts
├── next.config.ts
└── package.json
```

---

## Tailwind Config Skeleton

```ts
// tailwind.config.ts
import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#16533A',
          hover:   '#124430',
          light:   '#E8F5F0',
        },
        accent: {
          DEFAULT: '#3ECFAF',
          hover:   '#2EB89A',
        },
        surface: {
          DEFAULT: '#FFFFFF',
          raised:  '#FAFAFA',
        },
        border: {
          DEFAULT: '#E2E8E4',
          strong:  '#C8D4CE',
        },
        muted: '#6B7280',
      },
      borderRadius: {
        sm:   '4px',
        md:   '8px',
        lg:   '12px',
        xl:   '16px',
        full: '9999px',
      },
      boxShadow: {
        sm:    '0 1px 2px rgba(0,0,0,0.06)',
        md:    '0 4px 12px rgba(0,0,0,0.08)',
        lg:    '0 8px 24px rgba(0,0,0,0.10)',
        inner: 'inset 0 2px 4px rgba(0,0,0,0.04)',
      },
      fontFamily: {
        sans: ['Inter', 'var(--font-inter)', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'var(--font-jetbrains-mono)', 'monospace'],
      },
    },
  },
  plugins: [],
}

export default config
```

---

## App Icon Specification

**Concept: Mountain Pass with Route Line**

Three colors only:
- **Forest green** `#16533A` — background / primary shape
- **Mint** `#3ECFAF` — route line / accent
- **White** `#FFFFFF` — secondary shape details

**Shape**: Square canvas with `radius-xl` (standard app icon rounding). The icon renders correctly on iOS (system applies rounding) and on Android/web (apply rounding in SVG/PNG).

**Visual**: Two simplified mountain silhouettes (symmetric, abstract triangles) in white, low on the canvas. A bold mint route line (thick, ~8% canvas width) originates from the bottom-left, arcs upward through the gap between the mountains (the "pass"), and exits top-right with a subtle arrow-head. The overall feel is a clean geometric illustration — not a photo, not a gradient blob.

**Proportions**: Mountains occupy ~40% of canvas height. Route line: center of visual weight. Negative space: generous — the green background breathes.

See icon prompt below in the Gemini section.
