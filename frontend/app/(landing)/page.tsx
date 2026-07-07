'use client'

import Link from 'next/link'
import { useState, useEffect, useRef } from 'react'
import { motion, AnimatePresence, useScroll, useMotionValueEvent, useInView } from 'framer-motion'
import {
  Shield, Server, SlidersHorizontal, Code2,
  CheckCircle2, ChevronDown, ArrowRight, Zap,
  GitMerge, Globe, Webhook,
} from 'lucide-react'
import { Button } from '@/components/ui'
import {
  RoutePassIcon,
  type PlatformKey, PLATFORM_COLORS,
} from '@/components/platform-icons'
import { BrandIcon, BrandBadge } from '@/components/brand-box'

// ─── Animation helpers ───────────────────────────────────────────────────────

// For above-the-fold content — CSS transition driven by useEffect.
// Immune to React 18 Strict Mode double-invocation that breaks Framer Motion delays.
function FadeInMount({ children, delay = 0, className = '' }: {
  children: React.ReactNode
  delay?: number
  className?: string
}) {
  const [show, setShow] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setShow(true), delay * 1000)
    return () => clearTimeout(t)
  }, [delay])
  return (
    <div
      className={className}
      style={{
        opacity: show ? 1 : 0,
        transform: show ? 'translateY(0)' : 'translateY(14px)',
        transition: `opacity 0.5s cubic-bezier(0.22,1,0.36,1), transform 0.5s cubic-bezier(0.22,1,0.36,1)`,
        transitionDelay: '0ms',
      }}
    >
      {children}
    </div>
  )
}

// For below-the-fold content — uses native IntersectionObserver (not Framer Motion)
// so it works reliably in all contexts including iframes.
function FadeInUp({ children, delay = 0, className = '' }: {
  children: React.ReactNode
  delay?: number
  className?: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [inView, setInView] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const obs = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) { setInView(true); obs.disconnect() } },
      { rootMargin: '0px 0px -30px 0px' },
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  return (
    <div
      ref={ref}
      className={className}
      style={{
        opacity: inView ? 1 : 0,
        transform: inView ? 'translateY(0)' : 'translateY(16px)',
        transition: `opacity 0.5s cubic-bezier(0.22,1,0.36,1) ${delay}s, transform 0.5s cubic-bezier(0.22,1,0.36,1) ${delay}s`,
      }}
    >
      {children}
    </div>
  )
}

// ─── Hub visualization ───────────────────────────────────────────────────────

const HUB_PLATFORMS: {
  key: PlatformKey
  label: string
  live: boolean
}[] = [
  { key: 'strava',        label: 'Strava',          live: true },
  { key: 'komoot',        label: 'Komoot',           live: true },
  { key: 'intervals_icu', label: 'Intervals.icu',    live: false },
  { key: 'runalyze',      label: 'Runalyze',         live: false },
  { key: 'garmin',        label: 'Garmin',           live: false },
  { key: 'polar',         label: 'Polar',            live: false },
  { key: 'suunto',        label: 'Suunto',           live: false },
  { key: 'wahoo',         label: 'Wahoo',            live: false },
  { key: 'trainingpeaks', label: 'TrainingPeaks',    live: false },
  { key: 'webhook',       label: 'Webhooks',         live: true },
]

// SVG dimensions
const CX = 220
const CY = 220
const ORBIT_R = 170

function hubPosition(i: number, n: number) {
  const angle = (i / n) * 2 * Math.PI - Math.PI / 2
  return {
    x: CX + ORBIT_R * Math.cos(angle),
    y: CY + ORBIT_R * Math.sin(angle),
  }
}

function HubVisualization() {
  const n = HUB_PLATFORMS.length

  return (
    <div className="relative w-full max-w-[440px] mx-auto select-none">
      <svg viewBox={`0 0 ${CX * 2} ${CY * 2}`} className="w-full h-auto overflow-visible">
        <defs>
          {/* Radial glow behind center */}
          <radialGradient id="centerGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#3ecfaf" stopOpacity="0.25" />
            <stop offset="100%" stopColor="#3ecfaf" stopOpacity="0" />
          </radialGradient>
          {/* Gradient for each spoke line */}
          {HUB_PLATFORMS.map((p, i) => {
            const pos = hubPosition(i, n)
            return (
              <linearGradient
                key={p.key}
                id={`grad-${p.key}`}
                x1={pos.x}
                y1={pos.y}
                x2={CX}
                y2={CY}
                gradientUnits="userSpaceOnUse"
              >
                <stop offset="0%" stopColor={PLATFORM_COLORS[p.key]} stopOpacity={p.live ? 0.6 : 0.25} />
                <stop offset="100%" stopColor="#3ecfaf" stopOpacity="0.5" />
              </linearGradient>
            )
          })}
        </defs>

        {/* Outer orbit ring */}
        <circle
          cx={CX} cy={CY} r={ORBIT_R}
          fill="none"
          stroke="rgba(255,255,255,0.04)"
          strokeWidth="1"
        />

        {/* Spoke lines */}
        {HUB_PLATFORMS.map((p, i) => {
          const pos = hubPosition(i, n)
          return (
            <motion.line
              key={p.key}
              x1={pos.x} y1={pos.y}
              x2={CX} y2={CY}
              stroke={`url(#grad-${p.key})`}
              strokeWidth={p.live ? 1.5 : 0.75}
              strokeDasharray="4 4"
              initial={{ pathLength: 0, opacity: 0 }}
              animate={{ pathLength: 1, opacity: 1 }}
              transition={{ duration: 0.8, delay: i * 0.1, ease: 'easeOut' }}
            />
          )
        })}

        {/* Animated data-packet dots traveling each spoke */}
        {HUB_PLATFORMS.filter((p) => p.live).map((p, i) => {
          const pos = hubPosition(HUB_PLATFORMS.indexOf(p), n)
          return (
            <motion.circle
              key={`dot-${p.key}`}
              r={3}
              fill={PLATFORM_COLORS[p.key]}
              initial={{ cx: pos.x, cy: pos.y, opacity: 0 }}
              animate={{
                cx:      [pos.x, CX, pos.x],
                cy:      [pos.y, CY, pos.y],
                opacity: [0, 0.9, 0],
              }}
              transition={{
                duration:   2.4,
                delay:      i * 0.6 + 0.5,
                repeat:     Infinity,
                repeatDelay: 1.2,
                ease: 'easeInOut',
              }}
            />
          )
        })}

        {/* Center glow */}
        <circle cx={CX} cy={CY} r={70} fill="url(#centerGlow)" />

        {/* Center hub ring */}
        <circle
          cx={CX} cy={CY} r={42}
          fill="#111111"
          stroke="#3ecfaf"
          strokeWidth="1.5"
        />
        <motion.circle
          cx={CX} cy={CY} r={42}
          fill="none"
          stroke="#3ecfaf"
          strokeWidth="1"
          opacity={0.3}
          animate={{ r: [42, 52, 42], opacity: [0.3, 0, 0.3] }}
          transition={{ duration: 2.5, repeat: Infinity, ease: 'easeOut' }}
        />

        {/* RoutePass icon in center */}
        <foreignObject x={CX - 18} y={CY - 18} width={36} height={36}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 36, height: 36 }}>
            <RoutePassIcon size={30} />
          </div>
        </foreignObject>

        {/* Platform nodes */}
        {HUB_PLATFORMS.map((p, i) => {
          const pos = hubPosition(i, n)
          return (
            <motion.g
              key={p.key}
              initial={{ scale: 0, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ duration: 0.4, delay: i * 0.07 + 0.2 }}
              style={{ transformOrigin: `${pos.x}px ${pos.y}px` }}
            >
              <foreignObject
                x={pos.x - 36}
                y={pos.y - 36}
                width={72}
                height={72}
              >
                <div className="flex items-center justify-center w-full h-full relative">
                  <div
                    className="flex flex-col items-center justify-center gap-1 rounded-full relative z-10 w-full h-full"
                    style={{
                      background: '#1a1a1a',
                      border: `${p.live ? 1.5 : 1}px solid ${p.live ? PLATFORM_COLORS[p.key] : 'rgba(255,255,255,0.1)'}`,
                    }}
                  >
                    <BrandIcon
                      brand={p.key}
                      size={['runalyze', 'wahoo', 'suunto'].includes(p.key) ? 24 : 16}
                      variant={p.live ? 'regular' : 'white'}
                    />
                    {!['runalyze', 'wahoo', 'suunto'].includes(p.key) && (
                      <span className="text-[8.5px] leading-tight font-semibold text-center px-1" style={{ color: p.live ? 'rgba(255,255,255,0.9)' : 'rgba(255,255,255,0.4)' }}>
                        {p.label === 'Garmin Connect' ? 'Garmin' : p.label}
                      </span>
                    )}
                  </div>
                  {!p.live && (
                    <div className="absolute inset-0 bg-black/45 rounded-full z-20 pointer-events-none" />
                  )}
                </div>
              </foreignObject>
            </motion.g>
          )
        })}
      </svg>

      {/* Legend */}
      <div className="flex items-center justify-center gap-4 mt-2">
        <span className="flex items-center gap-1.5 text-xs text-white/40">
          <span className="w-2 h-2 rounded-full bg-[#3ecfaf] inline-block" />
          Live
        </span>
        <span className="flex items-center gap-1.5 text-xs text-white/25">
          <span className="w-2 h-2 rounded-full bg-white/20 inline-block" />
          Coming soon
        </span>
      </div>
    </div>
  )
}

// ─── Data ────────────────────────────────────────────────────────────────────

const INTEGRATIONS = [
  { key: 'strava' as PlatformKey,        label: 'Strava',         live: true },
  { key: 'komoot' as PlatformKey,        label: 'Komoot',          live: true },
  { key: 'intervals_icu' as PlatformKey, label: 'Intervals.icu',   live: false },
  { key: 'runalyze' as PlatformKey,      label: 'Runalyze',        live: false },
  { key: 'garmin' as PlatformKey,        label: 'Garmin Connect',  live: false },
  { key: 'polar' as PlatformKey,         label: 'Polar',           live: false },
  { key: 'suunto' as PlatformKey,        label: 'Suunto',          live: false },
  { key: 'wahoo' as PlatformKey,         label: 'Wahoo',           live: false },
  { key: 'trainingpeaks' as PlatformKey, label: 'TrainingPeaks',   live: false },
  { key: 'webhook' as PlatformKey,       label: 'Webhooks',        live: true },
]

const STEPS = [
  {
    n: '01',
    icon: Zap,
    title: 'Connect a platform',
    body: 'Authorize any supported platform — OAuth where available, credentials always encrypted.',
  },
  {
    n: '02',
    icon: GitMerge,
    title: 'Define a pipeline',
    body: 'Pick a source + destination. Any platform can be either end of the pipe.',
  },
  {
    n: '03',
    icon: SlidersHorizontal,
    title: 'Add sync rules',
    body: 'Filter by sport, distance, or name. Transform, rename, or skip on the fly.',
  },
  {
    n: '04',
    icon: Globe,
    title: 'Activities flow automatically',
    body: 'RoutePass watches 24/7 and routes every new activity to its destinations.',
  },
]

const FEATURES = [
  {
    icon: Globe,
    title: 'Any source, any destination',
    body: 'Every platform is a peer — Strava can be source or destination, same as Komoot or Intervals.icu.',
  },
  {
    icon: GitMerge,
    title: 'Multi-pipeline routing',
    body: 'Fan-out one source to many destinations, or funnel many sources into one. Independent rule chains per pipe.',
  },
  {
    icon: Shield,
    title: 'Rate-limit safe',
    body: 'Shared Strava quota managed across all users. Pro always gets first priority. No surprise API bans.',
  },
  {
    icon: Server,
    title: 'Self-hostable',
    body: 'AGPL-licensed. Run the full stack on your own hardware, bring your own credentials.',
  },
  {
    icon: SlidersHorizontal,
    title: 'Rule engine',
    body: 'Conditions + actions per pipeline. Match sport type, distance, elevation, name — then transform or skip.',
  },
  {
    icon: Code2,
    title: 'REST API + webhooks',
    body: 'Pro users get API keys and outbound signed webhooks to build custom integrations.',
  },
]

const PRICING = [
  {
    name: 'Free',
    price: '$0',
    period: 'forever',
    badge: null,
    highlight: false,
    features: [
      'Komoot → Strava sync',
      '~2 hour batch delay',
      '30 days of history on setup',
      '1 sync rule',
      'Dashboard access',
    ],
    cta: 'Get started free',
    ctaHref: '/register',
    variant: 'secondary-dark' as const,
  },
  {
    name: 'Pro',
    price: '$29',
    period: '/ year  ·  $3.49/mo',
    badge: 'Most popular',
    highlight: true,
    features: [
      'All sources + destinations',
      'Sync within ~10 minutes',
      '12-month history backfill',
      '5 sync rules per pipeline',
      'REST API + outbound webhooks',
      'Email support',
    ],
    cta: 'Get started',
    ctaHref: '/register',
    variant: 'accent' as const,
  },
  {
    name: 'Lifetime',
    price: '$79',
    period: 'one-time',
    badge: 'Limited · ~200 slots',
    highlight: false,
    features: [
      'All Pro features, forever',
      'No recurring payments',
      'Early-adopter pricing',
      'Priority support',
    ],
    cta: 'Buy once',
    ctaHref: '/register',
    variant: 'secondary-dark' as const,
  },
]

const FAQ = [
  {
    q: 'Which platforms are supported?',
    a: 'Live today: Komoot, Strava, Intervals.icu, Runalyze, and outbound webhooks. On the roadmap: Garmin Connect, Polar, Wahoo, and TrainingPeaks — added based on user demand.',
  },
  {
    q: 'Can a platform be both source and destination?',
    a: 'Yes. Every platform is a peer — there is no fixed source/destination distinction at the platform level. You define direction per-pipeline. Strava can receive activities from Komoot and also push webhook events outbound.',
  },
  {
    q: 'Can I send activities to my own system?',
    a: 'Yes. Pro users can configure outbound webhooks — RoutePass will POST a signed JSON payload to your URL on every sync. You can also pull via the REST API with an API key.',
  },
  {
    q: 'Is my data safe?',
    a: 'We never retain GPX files after upload. OAuth credentials are encrypted with AES-256 (Fernet) at rest. The source is public — audit every line at github.com/dettinjo/routepass.',
  },
  {
    q: 'What\'s the real difference between Free and Pro?',
    a: 'Sync speed (~10 min vs ~2 hr), history depth (12 months vs 30 days), all destination platforms, the REST API, and outbound webhooks.',
  },
  {
    q: 'Can I self-host for free?',
    a: 'Yes. AGPL-licensed. Full stack, all features, your own API credentials — no cost, no restrictions.',
  },
  {
    q: 'Does the Lifetime plan ever expire?',
    a: 'No. One payment for all current and future Pro features. Capped at ~200 slots for sustainability.',
  },
]

// ─── Dark theme tokens (inlined — avoids polluting dashboard light theme) ────
const D = {
  bg:       '#080808',
  surface:  '#111111',
  card:     '#161616',
  border:   'rgba(255,255,255,0.08)',
  text:     '#ededed',
  sub:      'rgba(255,255,255,0.5)',
  accent:   '#3ecfaf',
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function LandingPage() {
  const [navOpaque, setNavOpaque] = useState(false)
  const [openFaq, setOpenFaq] = useState<number | null>(null)
  const { scrollY } = useScroll()

  useMotionValueEvent(scrollY, 'change', (y) => setNavOpaque(y > 40))

  return (
    <div style={{ background: D.bg, color: D.text }} className="min-h-screen font-sans antialiased">

      {/* ── Nav ── */}
      <header
        style={{
          background: navOpaque ? 'rgba(8,8,8,0.85)' : 'transparent',
          borderBottom: navOpaque ? `1px solid ${D.border}` : 'none',
          backdropFilter: navOpaque ? 'blur(12px)' : 'none',
        }}
        className="sticky top-0 z-50 transition-all duration-300"
      >
        <div className="flex items-center justify-between px-6 py-4 max-w-5xl mx-auto">
          <Link href="/" className="flex items-center gap-2.5 hover:opacity-80 transition-opacity" style={{ color: D.accent }}>
            <RoutePassIcon size={28} />
            <span className="text-[28px] font-semibold font-display tracking-tight leading-none">RoutePass</span>
          </Link>
          <nav className="hidden sm:flex items-center gap-6 text-sm" style={{ color: D.sub }}>
            <a href="#how-it-works" className="hover:text-white transition-colors">How it works</a>
            <a href="#integrations" className="hover:text-white transition-colors">Integrations</a>
            <a href="#pricing" className="hover:text-white transition-colors">Pricing</a>
            <a href="/docs" className="hover:text-white transition-colors">Docs</a>
          </nav>
          <div className="flex items-center gap-3">
            <Link href="/login" className="text-sm hover:text-white transition-colors" style={{ color: D.sub }}>
              Sign in
            </Link>
            <Button asChild variant="accent" size="sm">
              <Link href="/register">Get started</Link>
            </Button>
          </div>
        </div>
      </header>

      {/* ── Hero ── */}
      <section className="relative overflow-hidden pt-24 pb-16 px-6 text-center">
        {/* Dot-grid background */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            backgroundImage: `radial-gradient(circle, rgba(255,255,255,0.06) 1px, transparent 1px)`,
            backgroundSize: '28px 28px',
          }}
        />
        {/* Radial gradient overlay */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background: `radial-gradient(ellipse 80% 60% at 50% 0%, rgba(62,207,175,0.08) 0%, transparent 70%)`,
          }}
        />

        <div className="relative max-w-3xl mx-auto">
          <FadeInMount>
            {/* Badge */}
            <div className="inline-flex items-center gap-2 mb-6 px-3 py-1.5 rounded-full text-xs font-medium"
              style={{ border: `1px solid ${D.border}`, color: D.accent, background: 'rgba(62,207,175,0.06)' }}>
              <span className="w-1.5 h-1.5 rounded-full bg-[#3ecfaf] animate-pulse" />
              Now in beta
            </div>
          </FadeInMount>

          <FadeInMount delay={0.08}>
            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold leading-[1.1] tracking-tight mb-5">
              Connect any fitness platform.<br />
              <span style={{ color: D.accent }}>Route activities anywhere.</span>
            </h1>
          </FadeInMount>

          <FadeInMount delay={0.16}>
            <p className="text-lg max-w-xl mx-auto mb-8" style={{ color: D.sub }}>
              Middleware for your fitness data. Define pipelines between any supported platform,
              add sync rules, and let activities flow automatically — in any direction.
            </p>
          </FadeInMount>

          <FadeInMount delay={0.22}>
            <div className="flex gap-3 justify-center flex-wrap">
              <Button asChild variant="accent" size="lg">
                <Link href="/register">Get started free</Link>
              </Button>
              <Button asChild variant="ghost-dark" size="lg">
                <a href="#how-it-works">See how it works</a>
              </Button>
            </div>
          </FadeInMount>
        </div>
      </section>

      {/* ── Hub Visualization ── */}
      <section
        id="integrations"
        className="py-16 px-6"
        style={{ borderTop: `1px solid ${D.border}`, borderBottom: `1px solid ${D.border}` }}
      >
        <div className="max-w-5xl mx-auto">
          <FadeInUp>
            <p className="text-center text-sm font-medium uppercase tracking-widest mb-2" style={{ color: D.accent }}>
              Integrations
            </p>
            <h2 className="text-2xl sm:text-3xl font-bold text-center mb-3">
              Every platform is a peer
            </h2>
            <p className="text-center mb-10 max-w-md mx-auto text-sm" style={{ color: D.sub }}>
              No fixed sources or destinations. Any platform can send or receive activities.
              RoutePass is the hub — pipelines define the direction.
            </p>
          </FadeInUp>

          <HubVisualization />

          {/* Integration chips */}
          <FadeInUp delay={0.15}>
            <div className="flex flex-wrap gap-2 justify-center mt-10">
              {[...INTEGRATIONS].sort((a, b) => (a.live === b.live ? 0 : a.live ? -1 : 1)).map((p) => (
                <BrandBadge
                  key={p.key}
                  brand={p.key}
                  variant={p.live ? 'outline' : 'ghost'}
                  className={p.live ? "!bg-[#111111]" : "!bg-[#111111] !border-[rgba(255,255,255,0.08)]"}
                >
                  <span
                    className="text-xs px-1.5 py-0.5 rounded-full"
                    style={{
                      background: p.live ? 'rgba(62,207,175,0.15)' : 'rgba(255,255,255,0.06)',
                      color: p.live ? D.accent : D.sub,
                    }}
                  >
                    {p.live ? 'Live' : 'Soon'}
                  </span>
                </BrandBadge>
              ))}
            </div>
          </FadeInUp>
        </div>
      </section>

      {/* ── How It Works ── */}
      <section id="how-it-works" className="py-24 px-6">
        <div className="max-w-5xl mx-auto">
          <FadeInUp>
            <h2 className="text-2xl sm:text-3xl font-bold text-center mb-2">How it works</h2>
            <p className="text-center mb-14 text-sm" style={{ color: D.sub }}>
              Set it once. Forget it forever.
            </p>
          </FadeInUp>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {STEPS.map((step, i) => (
              <FadeInUp key={step.n} delay={i * 0.07}>
                <div
                  className="p-5 rounded-xl flex flex-col gap-3 h-full"
                  style={{ background: D.card, border: `1px solid ${D.border}` }}
                >
                  <span className="text-4xl font-bold" style={{ color: D.accent, lineHeight: 1 }}>
                    {step.n}
                  </span>
                  <step.icon className="h-5 w-5" style={{ color: D.accent }} aria-hidden />
                  <h3 className="font-semibold text-sm">{step.title}</h3>
                  <p className="text-sm leading-relaxed" style={{ color: D.sub }}>{step.body}</p>
                </div>
              </FadeInUp>
            ))}
          </div>
        </div>
      </section>

      {/* ── Features ── */}
      <section
        id="features"
        className="py-20 px-6"
        style={{ borderTop: `1px solid ${D.border}`, borderBottom: `1px solid ${D.border}`, background: D.surface }}
      >
        <div className="max-w-5xl mx-auto">
          <FadeInUp>
            <h2 className="text-2xl sm:text-3xl font-bold text-center mb-12">
              Built for data control
            </h2>
          </FadeInUp>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {FEATURES.map((f, i) => (
              <FadeInUp key={f.title} delay={i * 0.05}>
                <div
                  className="p-5 rounded-xl h-full"
                  style={{ background: D.card, border: `1px solid ${D.border}` }}
                >
                  <div
                    className="w-8 h-8 rounded-lg flex items-center justify-center mb-3"
                    style={{ background: 'rgba(62,207,175,0.1)' }}
                  >
                    <f.icon className="h-4 w-4" style={{ color: D.accent }} aria-hidden />
                  </div>
                  <h3 className="font-semibold text-sm mb-1">{f.title}</h3>
                  <p className="text-sm leading-relaxed" style={{ color: D.sub }}>{f.body}</p>
                </div>
              </FadeInUp>
            ))}
          </div>
        </div>
      </section>

      {/* ── Self-hosted callout ── */}
      <section className="py-20 px-6" style={{ borderBottom: `1px solid ${D.border}` }}>
        <div className="max-w-5xl mx-auto grid sm:grid-cols-2 gap-12 items-center">
          <FadeInUp>
            <p className="text-xs font-medium uppercase tracking-widest mb-3" style={{ color: D.accent }}>
              Open source · AGPL-3.0
            </p>
            <h2 className="text-xl sm:text-2xl font-bold mb-3">Prefer to run it yourself?</h2>
            <p className="text-sm leading-relaxed mb-5" style={{ color: D.sub }}>
              Full stack, all features, your own API credentials. Your fitness data never leaves
              your infrastructure, and you bring your own rate-limit budget.
            </p>
            <a
              href="https://github.com/dettinjo/routepass"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-sm font-medium hover:opacity-80 transition-opacity"
              style={{ color: D.accent }}
            >
              View on GitHub <ArrowRight className="h-3.5 w-3.5" />
            </a>
          </FadeInUp>
          <FadeInUp delay={0.1}>
            <div
              className="rounded-xl p-5 font-mono text-sm"
              style={{ background: '#0d0d0d', border: `1px solid ${D.border}` }}
            >
              <p className="text-xs mb-2" style={{ color: D.sub }}># one command to run everything</p>
              <p><span style={{ color: D.accent }}>docker</span> compose up -d</p>
              <p className="mt-4 text-xs" style={{ color: D.sub }}>
                # backend · frontend · postgres · redis · worker<br />
                # no license key · all features included
              </p>
            </div>
          </FadeInUp>
        </div>
      </section>

      {/* ── Pricing ── */}
      <section id="pricing" className="py-24 px-6">
        <div className="max-w-5xl mx-auto">
          <FadeInUp>
            <h2 className="text-2xl sm:text-3xl font-bold text-center mb-2">Simple pricing</h2>
            <p className="text-center mb-14 text-sm" style={{ color: D.sub }}>
              Free to start. Upgrade for faster sync, more history, and all platforms.
            </p>
          </FadeInUp>
          <div className="grid sm:grid-cols-3 gap-5 items-start">
            {PRICING.map((tier, i) => (
              <FadeInUp key={tier.name} delay={i * 0.07}>
                <motion.div
                  whileHover={{ y: -2 }}
                  transition={{ duration: 0.2 }}
                  className="rounded-xl p-6 flex flex-col gap-5 h-full"
                  style={{
                    background: tier.highlight ? D.surface : D.card,
                    border: tier.highlight
                      ? `1px solid ${D.accent}`
                      : `1px solid ${D.border}`,
                    boxShadow: tier.highlight ? `0 0 0 1px ${D.accent}20, 0 0 32px ${D.accent}0d` : 'none',
                  }}
                >
                  <div>
                    <div className="flex items-center gap-2 mb-3">
                      <p className="font-semibold text-sm">{tier.name}</p>
                      {tier.badge && (
                        <span
                          className="text-xs font-medium px-2 py-0.5 rounded-full"
                          style={{
                            background: tier.highlight ? 'rgba(62,207,175,0.15)' : 'rgba(255,255,255,0.08)',
                            color: tier.highlight ? D.accent : D.sub,
                          }}
                        >
                          {tier.badge}
                        </span>
                      )}
                    </div>
                    <p className="text-2xl font-bold">
                      {tier.price}
                      <span className="text-sm font-normal ml-1" style={{ color: D.sub }}>{tier.period}</span>
                    </p>
                  </div>
                  <ul className="space-y-2 flex-1">
                    {tier.features.map((f) => (
                      <li key={f} className="flex items-start gap-2 text-sm" style={{ color: D.sub }}>
                        <CheckCircle2 className="h-4 w-4 mt-0.5 shrink-0" style={{ color: D.accent }} aria-hidden />
                        {f}
                      </li>
                    ))}
                  </ul>
                  <Button asChild variant={tier.variant} className="w-full">
                    <Link href={tier.ctaHref}>{tier.cta}</Link>
                  </Button>
                </motion.div>
              </FadeInUp>
            ))}
          </div>
          <FadeInUp delay={0.25}>
            <p className="text-center text-xs mt-6" style={{ color: D.sub }}>
              30-day money-back guarantee · No credit card required for Free
            </p>
          </FadeInUp>
        </div>
      </section>

      {/* ── FAQ ── */}
      <section
        className="py-20 px-6"
        style={{ borderTop: `1px solid ${D.border}`, borderBottom: `1px solid ${D.border}`, background: D.surface }}
      >
        <div className="max-w-2xl mx-auto">
          <FadeInUp>
            <h2 className="text-2xl sm:text-3xl font-bold text-center mb-12">FAQ</h2>
          </FadeInUp>
          <div style={{ borderTop: `1px solid ${D.border}` }}>
            {FAQ.map((item, i) => (
              <FadeInUp key={i} delay={i * 0.04}>
                <div style={{ borderBottom: `1px solid ${D.border}` }}>
                  <button
                    className="w-full flex items-center justify-between py-5 text-left gap-4 group"
                    onClick={() => setOpenFaq(openFaq === i ? null : i)}
                    aria-expanded={openFaq === i}
                  >
                    <span className="font-medium text-sm group-hover:text-white transition-colors" style={{ color: openFaq === i ? '#fff' : D.text }}>
                      {item.q}
                    </span>
                    <motion.div animate={{ rotate: openFaq === i ? 180 : 0 }} transition={{ duration: 0.2 }}>
                      <ChevronDown className="h-4 w-4 shrink-0" style={{ color: D.sub }} aria-hidden />
                    </motion.div>
                  </button>
                  <AnimatePresence initial={false}>
                    {openFaq === i && (
                      <motion.div
                        key="body"
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
                        className="overflow-hidden"
                      >
                        <p className="text-sm leading-relaxed pb-5" style={{ color: D.sub }}>{item.a}</p>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              </FadeInUp>
            ))}
          </div>
        </div>
      </section>

      {/* ── Final CTA ── */}
      <section className="py-24 px-6 text-center relative overflow-hidden">
        <div
          className="absolute inset-0 pointer-events-none"
          style={{ background: `radial-gradient(ellipse 60% 70% at 50% 50%, rgba(62,207,175,0.07) 0%, transparent 70%)` }}
        />
        <FadeInUp>
          <Webhook className="h-8 w-8 mx-auto mb-5" style={{ color: D.accent, opacity: 0.6 }} aria-hidden />
          <h2 className="text-2xl sm:text-3xl font-bold mb-3">Start syncing for free.</h2>
          <p className="text-sm mb-8 max-w-sm mx-auto" style={{ color: D.sub }}>
            No credit card required. Connect your first pipeline in under two minutes.
          </p>
          <div className="flex gap-3 justify-center flex-wrap">
            <Button asChild variant="accent" size="lg">
              <Link href="/register">Get started free</Link>
            </Button>
            <Button asChild variant="ghost-dark" size="lg">
              <a href="/docs">Read the docs</a>
            </Button>
          </div>
        </FadeInUp>
      </section>

      {/* ── Footer ── */}
      <footer
        className="py-8 px-6 text-center text-xs"
        style={{ borderTop: `1px solid ${D.border}`, color: D.sub }}
      >
        © {new Date().getFullYear()} RoutePass ·{' '}
        <Link href="/privacy" className="hover:text-white transition-colors">Privacy</Link>
        {' · '}
        <Link href="/terms" className="hover:text-white transition-colors">Terms</Link>
        {' · '}
        <Link href="/imprint" className="hover:text-white transition-colors">Imprint</Link>
        {' · '}
        <a href="https://github.com/dettinjo/routepass" className="hover:text-white transition-colors" target="_blank" rel="noopener noreferrer">GitHub</a>
        {' · '}
        <a href="/docs" className="hover:text-white transition-colors">Docs</a>
      </footer>
    </div>
  )
}
