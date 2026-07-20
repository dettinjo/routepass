'use client'

import { useEffect, useState } from 'react'
import { Loader2, RefreshCw } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle, Button, Badge } from '@/components/ui'
import { formatCents } from '@/lib/utils'
import {
  useAdminGovernorConfig,
  useAdminGovernorState,
  useRecomputeGovernorState,
  useUpdateAdminGovernorConfig,
} from '@/hooks/use-admin'

function Slider({
  label,
  value,
  onChange,
  hint,
}: {
  label: string
  value: number
  onChange: (v: number) => void
  hint: string
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <label className="text-body-sm text-text-primary">{label}</label>
        <span className="text-body-sm text-text-secondary font-medium">{value}%</span>
      </div>
      <input
        type="range"
        min={0}
        max={100}
        step={5}
        value={value}
        onChange={(e) => onChange(parseInt(e.target.value, 10))}
        className="w-full accent-primary"
      />
      <p className="text-caption text-text-disabled mt-1">{hint}</p>
    </div>
  )
}

export function GovernorTab() {
  const { data: config, isLoading: loadingConfig } = useAdminGovernorConfig()
  const { data: state, isLoading: loadingState } = useAdminGovernorState()
  const { mutate: updateConfig, isPending: saving } = useUpdateAdminGovernorConfig()
  const { mutate: recompute, isPending: recomputing } = useRecomputeGovernorState()

  const [coverage, setCoverage] = useState(70)
  const [reservation, setReservation] = useState(40)
  const [degradationEnabled, setDegradationEnabled] = useState(true)
  const [infraCost, setInfraCost] = useState('0')

  useEffect(() => {
    if (config) {
      setCoverage(config.coverage_target_pct)
      setReservation(config.paid_reservation_pct)
      setDegradationEnabled(config.free_degradation_enabled)
      setInfraCost((config.infra_monthly_cost_cents / 100).toFixed(2))
    }
  }, [config])

  if (loadingConfig || loadingState || !config || !state) {
    return (
      <div className="flex items-center gap-2 text-text-secondary text-body-sm py-8">
        <Loader2 className="w-4 h-4 animate-spin" />
        Loading governor…
      </div>
    )
  }

  const dirty =
    coverage !== config.coverage_target_pct ||
    reservation !== config.paid_reservation_pct ||
    degradationEnabled !== config.free_degradation_enabled ||
    infraCost !== (config.infra_monthly_cost_cents / 100).toFixed(2)

  function save() {
    updateConfig({
      coverage_target_pct: coverage,
      paid_reservation_pct: reservation,
      free_degradation_enabled: degradationEnabled,
      infra_monthly_cost_cents: Math.round(parseFloat(infraCost || '0') * 100),
    })
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Live state</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="grid sm:grid-cols-2 gap-3 text-body-sm">
            <div className="flex items-center justify-between">
              <span className="text-text-secondary">Economic level</span>
              <Badge variant={state.economic_level >= 2 ? 'error' : state.economic_level >= 1 ? 'paused' : 'connected'}>
                {state.economic_level}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-text-secondary">Strava admission</span>
              <Badge variant={state.strava_admission_open ? 'connected' : 'error'}>
                {state.strava_admission_open ? 'open' : 'closed'}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-text-secondary">Cost</span>
              <span className="text-text-primary">{formatCents(state.monthly_cost_cents)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-text-secondary">Revenue (est.)</span>
              <span className="text-text-primary">{formatCents(state.monthly_revenue_cents)}</span>
            </div>
          </div>
          <p className="text-caption text-text-disabled pt-1">
            Computed {new Date(state.computed_at).toLocaleString()}
          </p>
          <Button variant="secondary" size="sm" loading={recomputing} onClick={() => recompute()}>
            <RefreshCw className="w-3.5 h-3.5" />
            Recompute now
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Configuration</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <Slider
            label="Coverage target"
            value={coverage}
            onChange={setCoverage}
            hint="Cost must stay at or below this % of revenue before degradation kicks in."
          />
          <Slider
            label="Paid reservation"
            value={reservation}
            onChange={setReservation}
            hint="Share of Strava athlete slots reserved for paid tiers."
          />
          <div className="flex items-center justify-between">
            <div>
              <p className="text-body-sm text-text-primary">Free-tier degradation</p>
              <p className="text-caption text-text-disabled">
                Disable to always treat free users as unlimited (not recommended in cloud mode).
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={degradationEnabled}
              onClick={() => setDegradationEnabled((v) => !v)}
              className={`relative inline-flex h-6 w-11 flex-shrink-0 rounded-full border-2 border-transparent
                transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2
                ${degradationEnabled ? 'bg-primary' : 'bg-border-strong'}`}
            >
              <span
                className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow
                  transition duration-200 ${degradationEnabled ? 'translate-x-5' : 'translate-x-0'}`}
              />
            </button>
          </div>
          <div>
            <label className="block text-body-sm text-text-primary mb-1">
              Infra monthly cost ($)
            </label>
            <input
              type="number"
              min={0}
              step={0.01}
              value={infraCost}
              onChange={(e) => setInfraCost(e.target.value)}
              className="w-32 h-9 px-3 text-body bg-surface-raised border border-border rounded-md
                         text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
            />
          </div>
          {dirty && (
            <Button variant="primary" size="sm" loading={saving} onClick={save}>
              Save configuration
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
