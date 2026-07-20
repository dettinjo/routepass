'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard,
  Activity,
  RefreshCw,
  Plug,
  GitMerge,
  Filter,
  Key,
  CreditCard,
  Settings2,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  ShieldCheck,
} from 'lucide-react'
import { cn, isPaidTier } from '@/lib/utils'
import { Badge } from '@/components/ui'
import { useAuthStore } from '@/store/auth'
import { useState } from 'react'

interface NavItem {
  href:    string
  label:   string
  icon:    React.ElementType
  proOnly?: boolean
  external?: boolean
  adminOnly?: boolean
}

const PRIMARY_NAV: NavItem[] = [
  { href: '/dashboard',    label: 'Dashboard',    icon: LayoutDashboard },
  { href: '/activities',   label: 'Activities',   icon: Activity },
  { href: '/connections',  label: 'Connections',  icon: Plug },
  { href: '/pipelines',    label: 'Pipelines',    icon: GitMerge },
  { href: '/rules',        label: 'Rules',        icon: Filter,   proOnly: true },
  { href: '/api-keys',     label: 'API Keys',     icon: Key,      proOnly: true },
]

const SECONDARY_NAV: NavItem[] = [
  { href: '/admin',     label: 'Admin',     icon: ShieldCheck, adminOnly: true },
  { href: '/billing',   label: 'Billing',   icon: CreditCard },
  { href: '/settings',  label: 'Settings',  icon: Settings2 },
  { href: 'https://routepass.online/docs', label: 'Docs', icon: ExternalLink, external: true },
]

export function Sidebar() {
  const pathname  = usePathname()
  const user      = useAuthStore((s) => s.user)
  const isPro     = isPaidTier(user?.tier)
  const isAdmin   = !!user?.is_admin
  const [collapsed, setCollapsed] = useState(false)
  const secondaryNav = SECONDARY_NAV.filter((item) => !item.adminOnly || isAdmin)

  return (
    <aside
      className={cn(
        'hidden md:flex flex-col border-r border-border bg-surface transition-all duration-200',
        collapsed ? 'w-16' : 'w-60',
      )}
      style={{ minHeight: 'calc(100vh - var(--topbar-height))' }}
    >
      {/* Primary nav */}
      <nav className="flex-1 px-3 py-4 space-y-1" aria-label="Main navigation">
        {PRIMARY_NAV.map((item) => (
          <NavLink
            key={item.href}
            item={item}
            active={pathname.startsWith(item.href)}
            isPro={isPro}
            collapsed={collapsed}
          />
        ))}
      </nav>

      {/* Divider */}
      <div className="mx-3 border-t border-border" />

      {/* Secondary nav */}
      <nav className="px-3 py-4 space-y-1" aria-label="Settings navigation">
        {secondaryNav.map((item) => (
          <NavLink
            key={item.href}
            item={item}
            active={pathname.startsWith(item.href)}
            isPro={isPro}
            collapsed={collapsed}
          />
        ))}
      </nav>

      {/* Collapse toggle */}
      <button
        onClick={() => setCollapsed((c) => !c)}
        className={cn(
          'flex items-center justify-center mx-3 mb-4 h-8 rounded-md',
          'text-text-secondary hover:bg-primary-light hover:text-primary',
          'transition-colors duration-150',
        )}
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        {!collapsed && <span className="ml-2 text-caption">Collapse</span>}
      </button>
    </aside>
  )
}

function NavLink({
  item,
  active,
  isPro,
  collapsed,
}: {
  item: NavItem
  active: boolean
  isPro: boolean
  collapsed: boolean
}) {
  const Icon  = item.icon
  const locked = item.proOnly && !isPro

  const linkProps = item.external
    ? { target: '_blank', rel: 'noopener noreferrer' }
    : {}

  return (
    <Link
      href={item.href}
      {...linkProps}
      className={cn(
        'flex items-center gap-3 rounded-md px-3 py-2 text-body-sm transition-colors duration-150',
        active
          ? 'bg-primary-light text-primary font-medium'
          : 'text-text-secondary hover:bg-surface-raised hover:text-text-primary',
        collapsed && 'justify-center px-2',
      )}
      aria-current={active ? 'page' : undefined}
    >
      <Icon className="h-4 w-4 flex-shrink-0" aria-hidden />
      {!collapsed && (
        <>
          <span className="flex-1 truncate">{item.label}</span>
          {item.proOnly && !isPro && (
            <Badge variant="pro" className="text-[10px] px-1.5">Pro</Badge>
          )}
          {item.external && (
            <ExternalLink className="h-3 w-3 opacity-40" aria-hidden />
          )}
        </>
      )}
    </Link>
  )
}
