'use client'

import { useState } from 'react'
import {
  GitMerge, Plus, RefreshCw, Trash2, Loader2,
  ChevronRight, AlertCircle, ToggleLeft, ToggleRight,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { BrandBox } from '@/components/brand-box'
import { useConnections } from '@/hooks/use-connections'
import {
  usePipelines,
  useCreatePipeline,
  useUpdatePipeline,
  useDeletePipeline,
  useTriggerPipelineSync,
} from '@/hooks/use-pipelines'
import type { Connection, Pipeline, PlatformKey } from '@/types/api'

// ── Create form ────────────────────────────────────────────────────────────────

function CreatePipelineForm({ connections, onClose }: { connections: Connection[]; onClose: () => void }) {
  const [sourceId, setSourceId] = useState('')
  const [destId, setDestId] = useState('')
  const [name, setName] = useState('')
  const { mutate: create, isPending, error } = useCreatePipeline()

  const activeConnections = connections.filter((c) => c.status === 'active')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!sourceId || !destId || !name.trim()) return
    create(
      { source_connection_id: sourceId, dest_connection_id: destId, name: name.trim() },
      { onSuccess: onClose },
    )
  }

  const selectCls =
    'w-full h-9 px-3 text-body bg-surface-raised border border-border rounded-md ' +
    'text-text-primary focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent'

  return (
    <form onSubmit={handleSubmit} className="space-y-4 pt-4 border-t border-border mt-4">
      <div className="grid sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-label text-text-secondary mb-1">Source (from)</label>
          <select value={sourceId} onChange={(e) => setSourceId(e.target.value)} required className={selectCls}>
            <option value="">Select source…</option>
            {activeConnections.map((c) => (
              <option key={c.id} value={c.id}>
                {c.display_name || c.platform}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-label text-text-secondary mb-1">Destination (to)</label>
          <select value={destId} onChange={(e) => setDestId(e.target.value)} required className={selectCls}>
            <option value="">Select destination…</option>
            {activeConnections
              .filter((c) => c.id !== sourceId)
              .map((c) => (
                <option key={c.id} value={c.id}>
                  {c.display_name || c.platform}
                </option>
              ))}
          </select>
        </div>
      </div>
      <div>
        <label className="block text-label text-text-secondary mb-1">Pipeline name</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Komoot → Strava"
          required
          className="w-full h-9 px-3 text-body bg-surface-raised border border-border rounded-md
                     text-text-primary placeholder:text-text-disabled
                     focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent"
        />
      </div>
      {error && <p className="text-body-sm text-error">{(error as Error).message}</p>}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" size="sm" loading={isPending}>
          Create pipeline
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

// ── Pipeline card ──────────────────────────────────────────────────────────────

function PipelineCard({
  pipeline,
  connections,
}: {
  pipeline: Pipeline
  connections: Connection[]
}) {
  const byId = Object.fromEntries(connections.map((c) => [c.id, c]))
  const source = byId[pipeline.source_connection_id]
  const dest = byId[pipeline.dest_connection_id]

  const { mutate: update, isPending: updating } = useUpdatePipeline()
  const { mutate: remove, isPending: deleting } = useDeletePipeline()
  const { mutate: sync, isPending: syncing } = useTriggerPipelineSync()

  function platformIcon(conn: Connection | undefined, side: 'source' | 'dest') {
    if (!conn) return <span className="text-text-disabled text-caption">Unknown</span>
    return (
      <div className="flex items-center gap-2">
        <BrandBox
          brand={conn.platform as PlatformKey}
          size={28}
          className="rounded-md"
          variant={pipeline.enabled ? 'regular' : 'inactive'}
        />
        <span className="text-body-sm text-text-primary truncate">
          {conn.display_name || conn.platform}
        </span>
      </div>
    )
  }

  return (
    <Card>
      <CardContent className="pt-5">
        <div className="flex items-center gap-4 flex-wrap">
          {/* Source → Dest */}
          <div className="flex items-center gap-2 flex-1 min-w-0">
            {platformIcon(source, 'source')}
            <ChevronRight className="w-4 h-4 text-text-disabled flex-shrink-0" />
            {platformIcon(dest, 'dest')}
          </div>

          {/* Name + enabled */}
          <div className="flex items-center gap-2 flex-shrink-0">
            <span className="text-body-sm text-text-secondary hidden sm:block">{pipeline.name}</span>
            <Badge variant={pipeline.enabled ? 'connected' : 'neutral'}>
              {pipeline.enabled ? 'Active' : 'Paused'}
            </Badge>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-1 flex-shrink-0">
            <Button
              variant="ghost"
              size="icon"
              title={pipeline.enabled ? 'Pause pipeline' : 'Resume pipeline'}
              loading={updating}
              onClick={() => update({ id: pipeline.id, enabled: !pipeline.enabled })}
            >
              {pipeline.enabled
                ? <ToggleRight className="w-4 h-4 text-success" />
                : <ToggleLeft className="w-4 h-4 text-text-disabled" />}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              title="Sync now"
              loading={syncing}
              disabled={!pipeline.enabled}
              onClick={() => sync(pipeline.id)}
            >
              <RefreshCw className="w-4 h-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              title="Delete pipeline"
              loading={deleting}
              onClick={() => remove(pipeline.id)}
            >
              <Trash2 className="w-4 h-4 text-error" />
            </Button>
          </div>
        </div>
        <p className="text-body-sm text-text-secondary mt-1 sm:hidden">{pipeline.name}</p>
      </CardContent>
    </Card>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function PipelinesPage() {
  const [creating, setCreating] = useState(false)
  const { data: pipelines, isLoading: pipelinesLoading } = usePipelines()
  const { data: connections, isLoading: connectionsLoading } = useConnections()

  const isLoading = pipelinesLoading || connectionsLoading
  const activeConnections = (connections ?? []).filter((c) => c.status === 'active')
  const canCreate = activeConnections.length >= 2

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-heading-xl text-text-primary">Pipelines</h1>
          <p className="text-body text-text-secondary mt-1">
            Route activities from a source platform to a destination.
          </p>
        </div>
        <Button
          variant="primary"
          size="sm"
          disabled={!canCreate || creating}
          onClick={() => setCreating(true)}
        >
          <Plus className="w-4 h-4" />
          New pipeline
        </Button>
      </div>

      {!canCreate && !isLoading && (
        <div className="flex items-start gap-3 px-4 py-3 rounded-md bg-warning-light text-warning text-body-sm">
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          You need at least two active connections to create a pipeline.{' '}
          <a href="/connections" className="underline">Connect platforms →</a>
        </div>
      )}

      {creating && canCreate && (
        <Card>
          <CardHeader>
            <CardTitle>New pipeline</CardTitle>
          </CardHeader>
          <CardContent>
            <CreatePipelineForm
              connections={activeConnections}
              onClose={() => setCreating(false)}
            />
          </CardContent>
        </Card>
      )}

      {isLoading ? (
        <div className="flex items-center gap-2 text-text-secondary text-body-sm py-8">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading pipelines…
        </div>
      ) : (pipelines ?? []).length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center">
            <GitMerge className="h-10 w-10 text-border-strong mb-4" aria-hidden />
            <h2 className="text-heading-md text-text-primary mb-2">No pipelines yet</h2>
            <p className="text-body text-text-secondary max-w-sm">
              A pipeline connects one source to one destination. Connect your platforms first,
              then create a pipeline to start syncing.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {(pipelines ?? []).map((p) => (
            <PipelineCard key={p.id} pipeline={p} connections={connections ?? []} />
          ))}
        </div>
      )}
    </div>
  )
}
