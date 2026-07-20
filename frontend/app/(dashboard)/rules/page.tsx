'use client'

import { useState } from 'react'
import { Filter, Plus, Trash2, Loader2, ToggleLeft, ToggleRight, Pencil, ArrowRight } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { BrandIcon } from '@/components/brand-box'
import { Button } from '@/components/ui/button'
import { useAuthStore } from '@/store/auth'
import { useRules, useCreateRule, useUpdateRule, useDeleteRule } from '@/hooks/use-rules'
import { isPaidTier } from '@/lib/utils'
import type { SyncRule } from '@/types/api'

// ── Condition types ────────────────────────────────────────────────────────────

type ConditionType = 'sport_type' | 'distance_km' | 'elevation_m' | 'name_contains'
type ActionType = 'skip' | 'set_sport_type' | 'name_template' | 'append_description'

interface SimpleRule {
  name: string
  direction: 'komoot_to_strava' | 'strava_to_komoot' | 'both'
  conditionType: ConditionType
  conditionOp: string
  conditionValue: string
  actionType: ActionType
  actionValue: string
  is_active: boolean
}

const CONDITION_LABELS: Record<ConditionType, string> = {
  sport_type: 'Sport type',
  distance_km: 'Distance (km)',
  elevation_m: 'Elevation (m)',
  name_contains: 'Name contains',
}

const ACTION_LABELS: Record<ActionType, string> = {
  skip: 'Skip (don\'t sync)',
  set_sport_type: 'Override sport type',
  name_template: 'Rename activity',
  append_description: 'Append to description',
}

// Convert simple form state → backend conditions/actions dicts
function toBackend(r: SimpleRule): {
  conditions: Record<string, unknown>
  actions: Record<string, unknown>
} {
  let conditions: Record<string, unknown> = {}

  if (r.conditionType === 'sport_type') {
    conditions = { sport_type: { is: r.conditionValue.split(',').map((s) => s.trim()).filter(Boolean) } }
  } else if (r.conditionType === 'distance_km') {
    const val = parseFloat(r.conditionValue)
    conditions = { distance_km: { [r.conditionOp]: isNaN(val) ? 0 : val } }
  } else if (r.conditionType === 'elevation_m') {
    const val = parseFloat(r.conditionValue)
    conditions = { elevation_m: { [r.conditionOp]: isNaN(val) ? 0 : val } }
  } else if (r.conditionType === 'name_contains') {
    conditions = { name_contains: r.conditionValue }
  }

  let actions: Record<string, unknown> = {}
  if (r.actionType === 'skip') {
    actions = { skip: true }
  } else if (r.actionType === 'set_sport_type') {
    actions = { set_sport_type: r.actionValue }
  } else if (r.actionType === 'name_template') {
    actions = { name_template: r.actionValue }
  } else if (r.actionType === 'append_description') {
    actions = { append_description: r.actionValue }
  }

  return { conditions, actions }
}

// Summarise conditions/actions JSON → readable string for the card
function summariseConditions(cond: Record<string, unknown>): string {
  const parts: string[] = []
  if (cond.sport_type && typeof cond.sport_type === 'object') {
    const st = cond.sport_type as Record<string, string[]>
    if (st.is) parts.push(`sport is ${st.is.join(', ')}`)
    if (st.is_not) parts.push(`sport not ${st.is_not.join(', ')}`)
  }
  if (cond.distance_km && typeof cond.distance_km === 'object') {
    const d = cond.distance_km as Record<string, number>
    if (d.gt !== undefined) parts.push(`distance > ${d.gt} km`)
    if (d.lt !== undefined) parts.push(`distance < ${d.lt} km`)
  }
  if (cond.elevation_m && typeof cond.elevation_m === 'object') {
    const e = cond.elevation_m as Record<string, number>
    if (e.gt !== undefined) parts.push(`elevation > ${e.gt} m`)
    if (e.lt !== undefined) parts.push(`elevation < ${e.lt} m`)
  }
  if (typeof cond.name_contains === 'string') parts.push(`name contains "${cond.name_contains}"`)
  return parts.join(' & ') || 'All activities'
}

function summariseActions(actions: Record<string, unknown>): string {
  if (actions.skip) return 'Skip'
  if (actions.set_sport_type) return `Set sport → ${actions.set_sport_type}`
  if (actions.name_template) return `Rename: ${actions.name_template}`
  if (actions.append_description) return `Append: "${actions.append_description}"`
  return JSON.stringify(actions)
}

// ── Rule form ──────────────────────────────────────────────────────────────────

const DEFAULT_RULE: SimpleRule = {
  name: '',
  direction: 'komoot_to_strava',
  conditionType: 'sport_type',
  conditionOp: 'gt',
  conditionValue: '',
  actionType: 'skip',
  actionValue: '',
  is_active: true,
}

function RuleForm({
  initial,
  ruleId,
  ruleOrder,
  onClose,
}: {
  initial?: SimpleRule
  ruleId?: string
  ruleOrder?: number
  onClose: () => void
}) {
  const [form, setForm] = useState<SimpleRule>(initial ?? DEFAULT_RULE)
  const { mutate: create, isPending: creating, error: createError } = useCreateRule()
  const { mutate: update, isPending: updating, error: updateError } = useUpdateRule()
  const isPending = creating || updating
  const error = createError || updateError

  const set = (k: keyof SimpleRule, v: string | boolean) =>
    setForm((f) => ({ ...f, [k]: v }))

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const { conditions, actions } = toBackend(form)
    const payload = {
      name: form.name.trim(),
      direction: form.direction,
      conditions,
      actions,
      rule_order: ruleOrder ?? 0,
      is_active: form.is_active,
    }
    if (ruleId) {
      update({ id: ruleId, ...payload }, { onSuccess: onClose })
    } else {
      create(payload, { onSuccess: onClose })
    }
  }

  const inputCls =
    'w-full h-9 px-3 text-body bg-surface-raised border border-border rounded-md ' +
    'text-text-primary placeholder:text-text-disabled ' +
    'focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent'

  const selectCls = inputCls

  const needsOp = form.conditionType === 'distance_km' || form.conditionType === 'elevation_m'
  const needsValue = form.actionType !== 'skip'

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* Name + direction */}
      <div className="grid sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-label text-text-secondary mb-1">Rule name</label>
          <input
            className={inputCls}
            placeholder="e.g. Skip hikes"
            value={form.name}
            onChange={(e) => set('name', e.target.value)}
            required
          />
        </div>
        <div>
          <label className="block text-label text-text-secondary mb-1">Direction</label>
          <select className={selectCls} value={form.direction} onChange={(e) => set('direction', e.target.value)}>
            <option value="komoot_to_strava">Komoot → Strava</option>
            <option value="strava_to_komoot">Strava → Komoot</option>
            <option value="both">Both directions</option>
          </select>
        </div>
      </div>

      {/* Condition */}
      <div>
        <p className="text-label text-text-secondary mb-2">When…</p>
        <div className="grid sm:grid-cols-3 gap-3">
          <select className={selectCls} value={form.conditionType} onChange={(e) => set('conditionType', e.target.value)}>
            {(Object.keys(CONDITION_LABELS) as ConditionType[]).map((k) => (
              <option key={k} value={k}>{CONDITION_LABELS[k]}</option>
            ))}
          </select>

          {needsOp && (
            <select className={selectCls} value={form.conditionOp} onChange={(e) => set('conditionOp', e.target.value)}>
              <option value="gt">is greater than</option>
              <option value="lt">is less than</option>
            </select>
          )}

          <div className={needsOp ? '' : 'sm:col-span-2'}>
            <input
              className={inputCls}
              placeholder={
                form.conditionType === 'sport_type'
                  ? 'hike, e_road_cycling, …'
                  : form.conditionType === 'name_contains'
                  ? 'keyword'
                  : '0'
              }
              value={form.conditionValue}
              onChange={(e) => set('conditionValue', e.target.value)}
              required
            />
          </div>
        </div>
        {form.conditionType === 'sport_type' && (
          <p className="text-caption text-text-disabled mt-1">
            Comma-separated Komoot sport types, e.g. <code>hike, jogging</code>
          </p>
        )}
      </div>

      {/* Action */}
      <div>
        <p className="text-label text-text-secondary mb-2">Then…</p>
        <div className="grid sm:grid-cols-2 gap-3">
          <select className={selectCls} value={form.actionType} onChange={(e) => set('actionType', e.target.value)}>
            {(Object.keys(ACTION_LABELS) as ActionType[]).map((k) => (
              <option key={k} value={k}>{ACTION_LABELS[k]}</option>
            ))}
          </select>
          {needsValue && (
            <input
              className={inputCls}
              placeholder={
                form.actionType === 'set_sport_type'
                  ? 'Ride, Run, Hike, …'
                  : form.actionType === 'name_template'
                  ? '{name} · {distance:.0f}km'
                  : '#komoot'
              }
              value={form.actionValue}
              onChange={(e) => set('actionValue', e.target.value)}
              required
            />
          )}
        </div>
      </div>

      {error && <p className="text-body-sm text-error">{(error as Error).message}</p>}

      <div className="flex gap-2">
        <Button type="submit" variant="primary" size="sm" loading={isPending}>
          {ruleId ? 'Save changes' : 'Create rule'}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

// ── Rule card ──────────────────────────────────────────────────────────────────

function RuleCard({ rule, index }: { rule: SyncRule; index: number }) {
  const [editing, setEditing] = useState(false)
  const { mutate: update, isPending: toggling } = useUpdateRule()
  const { mutate: remove, isPending: deleting } = useDeleteRule()

  const condSummary = summariseConditions(rule.conditions)
  const actSummary = summariseActions(rule.actions)

  if (editing) {
    return (
      <Card>
        <CardHeader><CardTitle>Edit rule</CardTitle></CardHeader>
        <CardContent>
          <RuleForm ruleId={rule.id} ruleOrder={rule.rule_order} onClose={() => setEditing(false)} />
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardContent className="pt-5">
        <div className="flex items-start gap-4">
          {/* Order badge */}
          <div className="flex-shrink-0 w-7 h-7 rounded-full bg-surface-raised border border-border
                          flex items-center justify-center text-label text-text-disabled">
            {index + 1}
          </div>

          {/* Info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-body text-text-primary font-medium">{rule.name}</span>
              <Badge variant={rule.is_active ? 'connected' : 'neutral'}>
                {rule.is_active ? 'Active' : 'Paused'}
              </Badge>
              <div className="flex items-center gap-1.5 px-2 py-0.5 rounded border border-border bg-surface">
                {rule.direction === 'komoot_to_strava' ? (
                  <>
                    <BrandIcon brand="komoot" size={12} variant={rule.is_active ? 'regular' : 'inactive'} />
                    <ArrowRight className="w-3 h-3 text-text-disabled" />
                    <BrandIcon brand="strava" size={12} variant={rule.is_active ? 'regular' : 'inactive'} />
                  </>
                ) : rule.direction === 'strava_to_komoot' ? (
                  <>
                    <BrandIcon brand="strava" size={12} variant={rule.is_active ? 'regular' : 'inactive'} />
                    <ArrowRight className="w-3 h-3 text-text-disabled" />
                    <BrandIcon brand="komoot" size={12} variant={rule.is_active ? 'regular' : 'inactive'} />
                  </>
                ) : (
                  <>
                    <BrandIcon brand="komoot" size={12} variant={rule.is_active ? 'regular' : 'inactive'} />
                    <ArrowRight className="w-3 h-3 text-text-disabled" />
                    <BrandIcon brand="strava" size={12} variant={rule.is_active ? 'regular' : 'inactive'} />
                    <span className="text-[10px] text-text-disabled uppercase font-medium leading-none ml-1">Both</span>
                  </>
                )}
              </div>
            </div>
            <p className="text-caption text-text-secondary mt-1">
              <span className="text-text-disabled">When</span> {condSummary}
              {' → '}
              <span className="text-text-disabled">then</span> {actSummary}
            </p>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-1 flex-shrink-0">
            <Button
              variant="ghost" size="icon"
              title={rule.is_active ? 'Pause rule' : 'Resume rule'}
              loading={toggling}
              onClick={() => update({
                id: rule.id,
                name: rule.name,
                direction: rule.direction,
                conditions: rule.conditions,
                actions: rule.actions,
                rule_order: rule.rule_order,
                is_active: !rule.is_active,
              })}
            >
              {rule.is_active
                ? <ToggleRight className="w-4 h-4 text-success" />
                : <ToggleLeft className="w-4 h-4 text-text-disabled" />}
            </Button>
            <Button variant="ghost" size="icon" title="Edit" onClick={() => setEditing(true)}>
              <Pencil className="w-4 h-4" />
            </Button>
            <Button
              variant="ghost" size="icon" title="Delete" loading={deleting}
              onClick={() => remove(rule.id)}
            >
              <Trash2 className="w-4 h-4 text-error" />
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function RulesPage() {
  const [creating, setCreating] = useState(false)
  const { data, isLoading } = useRules()
  const user = useAuthStore((s) => s.user)
  const isPro = isPaidTier(user?.tier)
  const rules = data?.data ?? []
  const limit = isPro ? 5 : 1
  const atLimit = rules.length >= limit

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-heading-xl text-text-primary flex items-center gap-2">
            Rules
            {!isPro && <Badge variant="pro">Pro</Badge>}
          </h1>
          <p className="text-body text-text-secondary mt-1">
            Automatically filter and transform activities during sync.
            Rules are evaluated top-to-bottom — first match wins.
          </p>
        </div>
        <Button
          variant="primary"
          size="sm"
          disabled={creating || atLimit}
          onClick={() => setCreating(true)}
          title={atLimit ? `${limit}-rule limit reached on your plan` : undefined}
        >
          <Plus className="w-4 h-4" />
          New rule
        </Button>
      </div>

      {atLimit && (
        <p className="text-body-sm text-text-secondary">
          {isPro
            ? 'You have reached the 5-rule limit for Pro plans.'
            : 'Free plan allows 1 rule. Upgrade to Pro for up to 5 rules.'}
          {!isPro && (
            <> <a href="/billing" className="text-primary hover:underline">Upgrade →</a></>
          )}
        </p>
      )}

      {creating && (
        <Card>
          <CardHeader><CardTitle>New rule</CardTitle></CardHeader>
          <CardContent>
            <RuleForm ruleOrder={rules.length} onClose={() => setCreating(false)} />
          </CardContent>
        </Card>
      )}

      {isLoading ? (
        <div className="flex items-center gap-2 text-text-secondary text-body-sm py-8">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading rules…
        </div>
      ) : rules.length === 0 && !creating ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center">
            <Filter className="h-10 w-10 text-border-strong mb-4" aria-hidden />
            <h2 className="text-heading-md text-text-primary mb-2">No rules yet</h2>
            <p className="text-body text-text-secondary max-w-sm">
              Create a rule to automatically skip, rename, or transform activities
              based on sport type, distance, elevation, or name.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {rules.map((rule, i) => (
            <RuleCard key={rule.id} rule={rule} index={i} />
          ))}
        </div>
      )}

      {rules.length > 0 && (
        <p className="text-caption text-text-disabled text-center">
          {rules.length} / {limit} rule{limit !== 1 ? 's' : ''} used
        </p>
      )}
    </div>
  )
}
