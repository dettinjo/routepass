'use client'

import Link from 'next/link'
import { LogOut, Settings2, User } from 'lucide-react'
import { useAuthStore } from '@/store/auth'
import { useRouter } from 'next/navigation'
import { RoutePassIcon } from '@/components/platform-icons'

export function Topbar() {
  const user   = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const router = useRouter()

  function handleLogout() {
    logout()
    router.push('/login')
  }

  return (
    <header
      className="sticky top-0 z-50 flex items-center justify-between px-6 bg-surface border-b border-border"
      style={{ height: 'var(--topbar-height)' }}
    >
      {/* Logo */}
      <Link
        href="/dashboard"
        className="flex items-center gap-2.5 text-primary hover:opacity-80 transition-opacity"
        aria-label="RoutePass home"
      >
        <RoutePassIcon size={28} />
        <span className="text-[28px] font-semibold font-display tracking-tight leading-none">RoutePass</span>
      </Link>

      {/* Right side */}
      <div className="flex items-center gap-4">
        {/* User menu */}
        {user ? (
          <UserMenu
            displayName={user.name || user.email.split('@')[0]}
            email={user.email}
            onLogout={handleLogout}
          />
        ) : (
          <Link href="/login" className="text-body-sm text-primary hover:underline">
            Sign in
          </Link>
        )}
      </div>
    </header>
  )
}

function UserMenu({ displayName, email, onLogout }: { displayName: string; email: string; onLogout: () => void }) {
  // Minimal dropdown — replace with Radix DropdownMenu when building full interactivity
  return (
    <div className="relative group">
      <button
        className="flex items-center gap-2 rounded-md px-2 py-1.5 text-body-sm text-text-secondary hover:bg-surface-raised transition-colors"
        aria-label="User menu"
      >
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary-light">
          <User className="h-4 w-4 text-primary" aria-hidden />
        </span>
        <span className="hidden md:block max-w-[140px] truncate">{displayName}</span>
      </button>

      {/* Dropdown */}
      <div className="absolute right-0 top-full mt-1 w-48 bg-surface border border-border rounded-lg shadow-lg py-1 hidden group-focus-within:block">
        <Link
          href="/settings"
          className="flex items-center gap-2 px-4 py-2 text-body-sm text-text-primary hover:bg-surface-raised"
        >
          <Settings2 className="h-4 w-4" aria-hidden />
          Settings
        </Link>
        <button
          onClick={onLogout}
          className="flex w-full items-center gap-2 px-4 py-2 text-body-sm text-error hover:bg-error-light"
        >
          <LogOut className="h-4 w-4" aria-hidden />
          Sign out
        </button>
      </div>
    </div>
  )
}
