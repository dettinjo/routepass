// Vercel-inspired dark auth layout — full dark bg, centered card, minimal chrome.

import Link from 'next/link'
import { RoutePassIcon } from '@/components/platform-icons'

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-bg flex flex-col relative overflow-hidden">
      {/* Subtle dot grid */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage: 'radial-gradient(circle, rgba(255,255,255,0.04) 1px, transparent 1px)',
          backgroundSize: '28px 28px',
        }}
      />
      {/* Top radial glow */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: 'radial-gradient(ellipse 60% 40% at 50% 0%, rgba(62,207,175,0.06) 0%, transparent 70%)',
        }}
      />

      {/* Wordmark */}
      <header className="relative flex items-center justify-center py-10">
        <Link
          href="/"
          className="flex items-center gap-2.5 text-primary hover:opacity-80 transition-opacity"
        >
          <RoutePassIcon size={28} />
          <span className="text-[28px] font-semibold font-display tracking-tight leading-none">RoutePass</span>
        </Link>
      </header>

      {/* Centered form */}
      <main className="relative flex-1 flex items-start justify-center px-4 pb-16">
        <div className="w-full max-w-sm">
          {children}
        </div>
      </main>

      <footer className="relative py-6 text-center text-xs text-text-secondary">
        © {new Date().getFullYear()} RoutePass ·{' '}
        <Link href="/privacy" className="hover:text-text-primary transition-colors">Privacy</Link>
        {' · '}
        <Link href="/terms" className="hover:text-text-primary transition-colors">Terms</Link>
        {' · '}
        <Link href="/imprint" className="hover:text-text-primary transition-colors">Imprint</Link>
      </footer>
    </div>
  )
}
