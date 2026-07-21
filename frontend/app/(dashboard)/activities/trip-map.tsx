'use client'

/**
 * TripMap — renders one Leaflet polyline per trip stage, colored from the
 * fixed categorical theme (globals.css --chart-cat-*). MUST only be loaded
 * via `next/dynamic` with `{ ssr: false }` — see activity-map.tsx for why.
 */

import { useEffect, useRef } from 'react'
import type { TripMapStage } from '@/types/api'

const CAT_TOKENS = [
  '--chart-cat-1', '--chart-cat-2', '--chart-cat-3', '--chart-cat-4',
  '--chart-cat-5', '--chart-cat-6', '--chart-cat-7', '--chart-cat-8',
]
// Beyond the 8 validated categorical slots, additional stages fold into a
// neutral color — identity still carries via the tooltip/legend, not hue.
const OVERFLOW_TOKEN = '--color-text-disabled'

// SVG stroke is a presentation attribute, not CSS, so `var(...)` won't resolve
// there — Leaflet's SVG renderer needs the literal hex, hence the lookup here.
function resolveToken(token: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(token).trim()
}

function stageColor(i: number): string {
  return resolveToken(CAT_TOKENS[i] ?? OVERFLOW_TOKEN)
}

interface TripMapProps {
  stages: TripMapStage[]
}

export function TripMap({ stages }: TripMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<import('leaflet').Map | null>(null)

  useEffect(() => {
    if (!containerRef.current || stages.length === 0) return
    let isMounted = true

    if (mapRef.current) {
      mapRef.current.remove()
      mapRef.current = null
    }

    if (!document.getElementById('leaflet-css')) {
      const link = document.createElement('link')
      link.id = 'leaflet-css'
      link.rel = 'stylesheet'
      link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'
      document.head.appendChild(link)
    }

    import('leaflet').then((L) => {
      if (!isMounted || !containerRef.current) return
      if (mapRef.current) return

      const container = containerRef.current
      if ((container as any)._leaflet_id) {
        ;(container as any)._leaflet_id = null
        container.innerHTML = ''
      }

      const map = L.map(container, { zoomControl: true })
      mapRef.current = map

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
      }).addTo(map)

      const allBounds: [number, number][] = []
      stages.forEach((stage, i) => {
        const latlngs = stage.points.map((p) => [p.lat, p.lon] as [number, number])
        if (latlngs.length === 0) return
        const color = stageColor(i) || '#6366f1'

        const polyline = L.polyline(latlngs, { color, weight: 3, opacity: 0.9 }).addTo(map)
        polyline.bindTooltip(stage.name ?? `Stage ${i + 1}`, { sticky: true })
        allBounds.push(...latlngs)

        L.circleMarker(latlngs[0], {
          radius: 5, fillColor: color, color: '#fff', weight: 1.5, fillOpacity: 1,
        }).addTo(map).bindTooltip(`${stage.name ?? `Stage ${i + 1}`} — start`)
      })

      if (allBounds.length > 0) {
        map.fitBounds(allBounds, { padding: [16, 16] })
      }
    })

    return () => {
      isMounted = false
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stages])

  return (
    <div
      ref={containerRef}
      className="w-full rounded-lg overflow-hidden border border-border"
      style={{ height: 320 }}
    />
  )
}

// For plain CSS usage (e.g. a legend dot's `style.background`), the `var(...)`
// form resolves normally — only Leaflet's SVG attributes need the literal hex.
export function stageColorVar(i: number): string {
  return `var(${CAT_TOKENS[i] ?? OVERFLOW_TOKEN})`
}
