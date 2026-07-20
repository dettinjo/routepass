'use client'

import { CheckCircle2, Loader2, ExternalLink, Calendar, AlertTriangle } from 'lucide-react'
import { Card, CardHeader, CardTitle, CardContent, CardFooter } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useBillingSubscription, useCheckout, useBillingPortal } from '@/hooks/use-billing'
import { formatRelative, isPaidTier } from '@/lib/utils'

const FREE_FEATURES = [
  'Komoot → Strava sync',
  'Batch sync (up to 30-min delay)',
  '30 days activity history',
  '1 sync rule',
]

const PRO_FEATURES = [
  'Everything in Free',
  'Near-realtime sync (10-min poll)',
  '24 months activity history',
  '5 sync rules',
  'Intervals.icu & Runalyze push',
  'API key access',
  'Priority support',
]

function StatusBadge({ status }: { status: string }) {
  if (status === 'active' || status === 'trialing') return <Badge variant="connected">{status}</Badge>
  if (status === 'past_due') return <Badge variant="error">Past due</Badge>
  if (status === 'canceled') return <Badge variant="neutral">Canceled</Badge>
  return <Badge variant="neutral">{status}</Badge>
}

export default function BillingPage() {
  const { data: sub, isLoading, error } = useBillingSubscription()
  const { mutate: checkout, isPending: checkingOut } = useCheckout()
  const { mutate: portal, isPending: openingPortal } = useBillingPortal()

  const isPro = isPaidTier(sub?.tier)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-heading-xl text-text-primary">Billing</h1>
        <p className="text-body text-text-secondary mt-1">
          Manage your RoutePass subscription.
        </p>
      </div>

      {/* Current plan summary */}
      {isLoading ? (
        <div className="flex items-center gap-2 text-text-secondary text-body-sm py-4">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading subscription…
        </div>
      ) : error ? (
        <div className="flex items-start gap-3 px-4 py-3 rounded-md bg-error-light text-error text-body-sm">
          <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          Could not load subscription details.
        </div>
      ) : sub && (
        <div className="flex flex-wrap items-center gap-3 px-5 py-4 rounded-lg bg-surface-raised border border-border">
          <div className="flex-1">
            <p className="text-body text-text-primary font-medium capitalize">
              {sub.tier} plan
            </p>
            {sub.current_period_end && (
              <p className="text-caption text-text-disabled mt-0.5 flex items-center gap-1">
                <Calendar className="w-3 h-3" />
                {sub.canceled_at ? 'Ends' : 'Renews'}{' '}
                {formatRelative(new Date(sub.current_period_end))}
              </p>
            )}
          </div>
          <StatusBadge status={sub.status} />
          {isPro && (
            <Button
              variant="secondary"
              size="sm"
              loading={openingPortal}
              onClick={() => portal()}
            >
              <ExternalLink className="w-3.5 h-3.5" />
              Manage subscription
            </Button>
          )}
        </div>
      )}

      {/* Plan cards */}
      <div className="grid md:grid-cols-2 gap-6 max-w-2xl">
        {/* Free */}
        <Card className={!isPro ? 'border-primary' : ''}>
          <CardHeader>
            <CardTitle>Free</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-heading-lg text-text-primary font-bold">$0</p>
            <ul className="space-y-2">
              {FREE_FEATURES.map((f) => (
                <li key={f} className="flex items-center gap-2 text-body-sm text-text-primary">
                  <CheckCircle2 className="h-4 w-4 text-success flex-shrink-0" aria-hidden />
                  {f}
                </li>
              ))}
            </ul>
          </CardContent>
          <CardFooter>
            {!isPro
              ? <Badge variant="connected" className="w-full justify-center py-1.5">Current plan</Badge>
              : <Badge variant="neutral" className="w-full justify-center py-1.5">Free</Badge>
            }
          </CardFooter>
        </Card>

        {/* Pro */}
        <Card className={isPro ? 'border-primary' : ''}>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Pro <Badge variant="pro">Pro</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-heading-lg text-text-primary font-bold">
              $4.99 <span className="text-body text-text-secondary font-normal">/ month</span>
            </p>
            <p className="text-caption text-text-secondary -mt-1">
              or $39 / year (save ~35%) · $99 lifetime
            </p>
            <ul className="space-y-2">
              {PRO_FEATURES.map((f) => (
                <li key={f} className="flex items-center gap-2 text-body-sm text-text-primary">
                  <CheckCircle2 className="h-4 w-4 text-primary flex-shrink-0" aria-hidden />
                  {f}
                </li>
              ))}
            </ul>
          </CardContent>
          <CardFooter className="flex-col gap-2 items-stretch">
            {isPro ? (
              <Badge variant="connected" className="w-full justify-center py-1.5">Current plan</Badge>
            ) : (
              <>
                <Button className="w-full" loading={checkingOut} onClick={() => checkout('pro_monthly')}>
                  Go Pro — $4.99/mo
                </Button>
                <div className="flex gap-2">
                  <Button variant="secondary" size="sm" className="flex-1" loading={checkingOut} onClick={() => checkout('pro_annual')}>
                    $39 / year
                  </Button>
                  <Button variant="secondary" size="sm" className="flex-1" loading={checkingOut} onClick={() => checkout('lifetime')}>
                    $99 lifetime
                  </Button>
                </div>
              </>
            )}
          </CardFooter>
        </Card>
      </div>
    </div>
  )
}
