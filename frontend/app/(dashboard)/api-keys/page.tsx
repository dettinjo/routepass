'use client'

import { useState } from 'react'
import {
  Key, Plus, Trash2, Loader2, Copy, CheckCircle2, AlertTriangle, Clock,
} from 'lucide-react'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useAuthStore } from '@/store/auth'
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from '@/hooks/use-api-keys'
import { formatRelative, isPaidTier } from '@/lib/utils'
import type { ApiKey, ApiKeyCreated } from '@/types/api'

// ── Newly-created key banner ───────────────────────────────────────────────────

function NewKeyBanner({ created, onDismiss }: { created: ApiKeyCreated; onDismiss: () => void }) {
  const [copied, setCopied] = useState(false)

  const copy = () => {
    navigator.clipboard.writeText(created.raw_key).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <div className="px-4 py-4 rounded-lg bg-success-light border border-success space-y-3">
      <div className="flex items-start gap-2">
        <CheckCircle2 className="w-4 h-4 text-success flex-shrink-0 mt-0.5" />
        <div>
          <p className="text-body-sm text-success font-medium">API key created — copy it now</p>
          <p className="text-caption text-success mt-0.5">
            This is the only time the full key will be shown.
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <code className="flex-1 px-3 py-2 bg-bg rounded-md text-body-sm text-text-primary font-mono break-all">
          {created.raw_key}
        </code>
        <Button variant="secondary" size="sm" onClick={copy}>
          {copied ? <CheckCircle2 className="w-4 h-4 text-success" /> : <Copy className="w-4 h-4" />}
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>
      <Button variant="ghost" size="sm" onClick={onDismiss}>Dismiss</Button>
    </div>
  )
}

// ── Create form ────────────────────────────────────────────────────────────────

function CreateKeyForm({ onCreated, onClose }: {
  onCreated: (k: ApiKeyCreated) => void
  onClose: () => void
}) {
  const [name, setName] = useState('')
  const { mutate: create, isPending, error } = useCreateApiKey()

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    create(name.trim(), { onSuccess: (k) => { onCreated(k); onClose() } })
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3 pt-4 border-t border-border mt-4">
      <div className="flex-1 min-w-48">
        <label className="block text-label text-text-secondary mb-1">Key name</label>
        <input
          className="w-full h-9 px-3 text-body bg-surface-raised border border-border rounded-md
                     text-text-primary placeholder:text-text-disabled
                     focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent"
          placeholder="e.g. Home server"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          autoFocus
        />
        {error && <p className="text-caption text-error mt-1">{(error as Error).message}</p>}
      </div>
      <Button type="submit" variant="primary" size="sm" loading={isPending}>Generate</Button>
      <Button type="button" variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
    </form>
  )
}

// ── Key row ────────────────────────────────────────────────────────────────────

function KeyRow({ apiKey }: { apiKey: ApiKey }) {
  const { mutate: revoke, isPending } = useRevokeApiKey()
  const isRevoked = !!apiKey.revoked_at

  return (
    <div className="flex items-center gap-4 px-6 py-3 hover:bg-surface-raised transition-colors">
      <Key className="w-4 h-4 text-text-disabled flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-body text-text-primary">{apiKey.name}</p>
        <p className="text-caption text-text-disabled font-mono">{apiKey.key_prefix}</p>
      </div>
      <div className="text-right space-y-0.5 flex-shrink-0">
        {isRevoked
          ? <Badge variant="error">Revoked</Badge>
          : <Badge variant="connected">Active</Badge>}
        <p className="text-caption text-text-disabled flex items-center gap-1 justify-end">
          <Clock className="w-3 h-3" />
          {apiKey.last_used_at
            ? `Used ${formatRelative(new Date(apiKey.last_used_at))}`
            : `Created ${formatRelative(new Date(apiKey.created_at))}`}
        </p>
      </div>
      {!isRevoked && (
        <Button variant="ghost" size="icon" title="Revoke" loading={isPending}
          onClick={() => revoke(apiKey.id)}>
          <Trash2 className="w-4 h-4 text-error" />
        </Button>
      )}
    </div>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function ApiKeysPage() {
  const [creating, setCreating] = useState(false)
  const [newKey, setNewKey] = useState<ApiKeyCreated | null>(null)
  const { data, isLoading } = useApiKeys()
  const user = useAuthStore((s) => s.user)
  const isPro = isPaidTier(user?.tier)
  const keys = data?.data ?? []
  const activeCount = keys.filter((k) => !k.revoked_at).length

  if (!isPro) {
    return (
      <div className="space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-heading-xl text-text-primary">API Keys</h1>
            <p className="text-body text-text-secondary mt-1">
              Authenticate programmatic access to the RoutePass API.
            </p>
          </div>
          <Badge variant="pro">Pro</Badge>
        </div>
        <div className="flex items-start gap-3 px-4 py-4 rounded-lg bg-primary-light text-primary text-body-sm">
          <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>
            API key access is a Pro feature.{' '}
            <a href="/billing" className="underline font-medium">Upgrade to Pro →</a>
          </span>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-heading-xl text-text-primary">API Keys</h1>
          <p className="text-body text-text-secondary mt-1">
            Authenticate programmatic access to the RoutePass API. Max 5 active keys.
          </p>
        </div>
        <Button
          variant="primary" size="sm"
          disabled={creating || activeCount >= 5}
          onClick={() => setCreating(true)}
        >
          <Plus className="w-4 h-4" />
          New key
        </Button>
      </div>

      {newKey && <NewKeyBanner created={newKey} onDismiss={() => setNewKey(null)} />}

      <Card>
        <CardHeader>
          <CardTitle>Your keys</CardTitle>
        </CardHeader>

        <CardContent className="p-0">
          {creating && (
            <div className="px-6">
              <CreateKeyForm onCreated={setNewKey} onClose={() => setCreating(false)} />
            </div>
          )}

          {isLoading ? (
            <div className="flex items-center gap-2 text-text-secondary text-body-sm px-6 py-8">
              <Loader2 className="w-4 h-4 animate-spin" />
              Loading keys…
            </div>
          ) : keys.length === 0 && !creating ? (
            <div className="flex flex-col items-center justify-center py-12 text-center px-6">
              <Key className="h-8 w-8 text-border-strong mb-3" aria-hidden />
              <p className="text-body-sm text-text-secondary">No API keys yet.</p>
              <p className="text-caption text-text-disabled mt-1">
                Generate a key to integrate RoutePass with your own tools.
              </p>
            </div>
          ) : (
            <div className="divide-y divide-border mt-2">
              {keys.map((k) => <KeyRow key={k.id} apiKey={k} />)}
            </div>
          )}
        </CardContent>
      </Card>

      <p className="text-caption text-text-disabled">
        Send keys as <code className="font-mono">Authorization: Bearer &lt;key&gt;</code>.
        Keys are hashed at rest and cannot be recovered if lost — store them securely.
      </p>
    </div>
  )
}
