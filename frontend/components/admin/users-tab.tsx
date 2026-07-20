'use client'

import { useState } from 'react'
import { AlertCircle, ChevronLeft, ChevronRight, Loader2, Search, X } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle, Badge, Button, Input } from '@/components/ui'
import { formatRelative } from '@/lib/utils'
import { useAdminUserDetail, useAdminUsers } from '@/hooks/use-admin'

const PAGE_SIZE = 25

function TierBadge({ tier, isComp }: { tier: string; isComp: boolean }) {
  if (isComp) return <Badge variant="pro">comp</Badge>
  if (tier === 'free') return <Badge variant="neutral">free</Badge>
  return <Badge variant="pro">{tier}</Badge>
}

function UserDetailPanel({ userId, onClose }: { userId: string; onClose: () => void }) {
  const { data: user, isLoading } = useAdminUserDetail(userId)

  return (
    <Card>
      <CardHeader className="flex items-center justify-between">
        <CardTitle>{isLoading ? 'Loading…' : user?.email}</CardTitle>
        <Button variant="ghost" size="sm" onClick={onClose}>
          <X className="w-4 h-4" />
        </Button>
      </CardHeader>
      <CardContent className="space-y-5">
        {isLoading || !user ? (
          <div className="flex items-center gap-2 text-text-secondary text-body-sm py-4">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading…
          </div>
        ) : (
          <>
            <div className="grid sm:grid-cols-2 gap-3 text-body-sm">
              <div className="flex justify-between">
                <span className="text-text-secondary">Tier</span>
                <TierBadge tier={user.tier} isComp={user.is_comp} />
              </div>
              <div className="flex justify-between">
                <span className="text-text-secondary">Subscription status</span>
                <span className="text-text-primary">{user.subscription_status ?? '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-secondary">Joined</span>
                <span className="text-text-primary">{formatRelative(new Date(user.created_at))}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-secondary">Last login</span>
                <span className="text-text-primary">
                  {user.last_login_at ? formatRelative(new Date(user.last_login_at)) : '—'}
                </span>
              </div>
            </div>

            <div>
              <p className="text-label text-text-secondary mb-2">Usage today</p>
              <div className="flex gap-4 text-body-sm">
                {Object.entries(user.usage_today).map(([platform, count]) => (
                  <span key={platform} className="text-text-primary">
                    {platform}: <span className="font-medium">{count}</span>
                  </span>
                ))}
              </div>
            </div>

            <div>
              <p className="text-label text-text-secondary mb-2">Connections</p>
              {user.connections.length === 0 ? (
                <p className="text-body-sm text-text-disabled">No connections.</p>
              ) : (
                <div className="space-y-2">
                  {user.connections.map((c) => (
                    <div
                      key={c.id}
                      className="flex items-start gap-2 text-body-sm p-2 rounded-md bg-surface-raised"
                    >
                      <div className="flex-1 min-w-0">
                        <span className="text-text-primary font-medium">{c.platform}</span>{' '}
                        <span className="text-text-disabled">{c.display_name}</span>
                        {c.last_error && (
                          <p className="text-caption text-error flex items-center gap-1 mt-1">
                            <AlertCircle className="w-3 h-3 flex-shrink-0" />
                            {c.last_error}
                          </p>
                        )}
                        {c.poll_interval_effective_min && (
                          <p className="text-caption text-text-disabled mt-0.5">
                            polls every {c.poll_interval_effective_min} min
                          </p>
                        )}
                      </div>
                      <Badge variant={c.status === 'error' ? 'error' : c.status === 'active' ? 'connected' : 'neutral'}>
                        {c.status}
                      </Badge>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div>
              <p className="text-label text-text-secondary mb-2">Recent jobs</p>
              {user.recent_jobs.length === 0 ? (
                <p className="text-body-sm text-text-disabled">No recent jobs.</p>
              ) : (
                <div className="space-y-1">
                  {user.recent_jobs.map((j, i) => (
                    <div key={i} className="flex items-center justify-between text-caption">
                      <span className="text-text-secondary">
                        {j.job_type} · {j.enqueued_at ? formatRelative(new Date(j.enqueued_at)) : '—'}
                      </span>
                      <Badge variant={j.status === 'failed' ? 'error' : j.status === 'completed' ? 'connected' : 'neutral'}>
                        {j.status}
                      </Badge>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

export function UsersTab() {
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { data, isLoading } = useAdminUsers({ limit: PAGE_SIZE, offset, search: search || undefined })

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Users</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="relative max-w-xs">
            <Search className="w-4 h-4 text-text-disabled absolute left-3 top-1/2 -translate-y-1/2" />
            <Input
              placeholder="Search by email…"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setOffset(0)
              }}
              className="pl-9"
            />
          </div>

          {isLoading || !data ? (
            <div className="flex items-center gap-2 text-text-secondary text-body-sm py-4">
              <Loader2 className="w-4 h-4 animate-spin" /> Loading…
            </div>
          ) : data.users.length === 0 ? (
            <p className="text-body-sm text-text-secondary py-4">No users found.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-body-sm">
                <thead>
                  <tr className="text-left text-caption text-text-secondary border-b border-border">
                    <th className="pb-2 pr-4">Email</th>
                    <th className="pb-2 pr-4">Tier</th>
                    <th className="pb-2 pr-4">Connections</th>
                    <th className="pb-2 pr-4">Errors</th>
                    <th className="pb-2 pr-4">Strava today</th>
                    <th className="pb-2">Joined</th>
                  </tr>
                </thead>
                <tbody>
                  {data.users.map((u) => (
                    <tr
                      key={u.id}
                      onClick={() => setSelectedId(u.id)}
                      className="border-b border-border last:border-0 cursor-pointer hover:bg-surface-raised"
                    >
                      <td className="py-2 pr-4 text-text-primary">{u.email}</td>
                      <td className="py-2 pr-4">
                        <TierBadge tier={u.tier} isComp={u.is_comp} />
                      </td>
                      <td className="py-2 pr-4 text-text-secondary">{u.connections_count}</td>
                      <td className="py-2 pr-4">
                        {u.error_connections_count > 0 ? (
                          <Badge variant="error">{u.error_connections_count}</Badge>
                        ) : (
                          <span className="text-text-disabled">0</span>
                        )}
                      </td>
                      <td className="py-2 pr-4 text-text-secondary">{u.strava_requests_today}</td>
                      <td className="py-2 text-text-secondary">
                        {formatRelative(new Date(u.created_at))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="flex items-center justify-between mt-4 text-body-sm text-text-secondary">
                <span>
                  {offset + 1}–{Math.min(offset + PAGE_SIZE, data.total)} of {data.total}
                </span>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={offset === 0}
                    onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={offset + PAGE_SIZE >= data.total}
                    onClick={() => setOffset((o) => o + PAGE_SIZE)}
                  >
                    <ChevronRight className="w-4 h-4" />
                  </Button>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {selectedId && <UserDetailPanel userId={selectedId} onClose={() => setSelectedId(null)} />}
    </div>
  )
}
