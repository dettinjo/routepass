'use client'

import { useState } from 'react'
import { ShieldAlert } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/store/auth'
import { OverviewTab } from '@/components/admin/overview-tab'
import { ProvidersTab } from '@/components/admin/providers-tab'
import { GovernorTab } from '@/components/admin/governor-tab'
import { UsersTab } from '@/components/admin/users-tab'

type Tab = 'overview' | 'providers' | 'governor' | 'users'

const TABS: { id: Tab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'providers', label: 'Providers' },
  { id: 'governor', label: 'Governor' },
  { id: 'users', label: 'Users' },
]

export default function AdminPage() {
  const user = useAuthStore((s) => s.user)
  const [tab, setTab] = useState<Tab>('overview')

  if (!user?.is_admin) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
        <ShieldAlert className="w-10 h-10 text-text-disabled" />
        <p className="text-body text-text-secondary">
          You don&rsquo;t have admin access to this instance.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-heading-xl text-text-primary">Admin</h1>
        <p className="text-body text-text-secondary mt-1">
          API limits, cost, and per-user rate insight for this instance.
        </p>
      </div>

      <div className="flex gap-1 border-b border-border">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              'px-4 py-2 text-body-sm font-medium border-b-2 -mb-px transition-colors',
              tab === t.id
                ? 'border-primary text-text-primary'
                : 'border-transparent text-text-secondary hover:text-text-primary',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && <OverviewTab />}
      {tab === 'providers' && <ProvidersTab />}
      {tab === 'governor' && <GovernorTab />}
      {tab === 'users' && <UsersTab />}
    </div>
  )
}
