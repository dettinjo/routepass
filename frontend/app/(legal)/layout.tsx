import Link from 'next/link'
import { RoutePassIcon } from '@/components/platform-icons'

export default function LegalLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-bg flex flex-col">
      <header className="border-b border-border">
        <div className="container flex items-center justify-between py-6">
          <Link href="/" className="flex items-center gap-2.5 text-text-primary hover:opacity-80 transition-opacity">
            <RoutePassIcon size={24} />
            <span className="text-lg font-semibold font-display tracking-tight leading-none">RoutePass</span>
          </Link>
          <nav className="flex items-center gap-5 text-sm text-text-secondary">
            <Link href="/privacy" className="hover:text-text-primary transition-colors">Privacy</Link>
            <Link href="/terms" className="hover:text-text-primary transition-colors">Terms</Link>
            <Link href="/imprint" className="hover:text-text-primary transition-colors">Imprint</Link>
            <Link href="/docs" className="hover:text-text-primary transition-colors">Docs</Link>
          </nav>
        </div>
      </header>

      <main className="flex-1">
        <div className="container max-w-3xl py-14">
          {children}
        </div>
      </main>

      <footer className="border-t border-border py-6 text-center text-xs text-text-secondary">
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
