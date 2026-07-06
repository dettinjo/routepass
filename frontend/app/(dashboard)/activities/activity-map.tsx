'use client'

/**
 * ActivityMap — renders a Leaflet route map for a single activity.
 *
 * This file MUST only be loaded via `next/dynamic` with `{ ssr: false }` in
 * the parent page. Leaflet manipulates `window` / `document` at import time
 * and will crash during SSR. The dynamic wrapper ensures the entire module
 * (including the `import('leaflet')` call below) is never evaluated on the
 * server or included in the initial JS bundle, preventing the
 * ChunkLoadError that occurs when Next.js tries to serve the Leaflet chunk
 * before the client hydrates.
 */

import { useEffect, useRef } from 'react'

import type { LatLon } from './gpx-utils'

export type { LatLon }

interface ActivityMapProps {
  points: LatLon[]
}

export function ActivityMap({ points }: ActivityMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  // Keep map instance across renders without triggering re-renders
  const mapRef = useRef<import('leaflet').Map | null>(null)

  useEffect(() => {
    if (!containerRef.current || points.length === 0) return
    let isMounted = true

    if (mapRef.current) {
      mapRef.current.remove()
      mapRef.current = null
    }

    // Leaflet imports its own CSS; we inject it once if not already present
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
      // If the container still has a leaflet ID (e.g. from hot reload or concurrent strict mode execution),
      // we must reset it before initializing a new map.
      if ((container as any)._leaflet_id) {
        ;(container as any)._leaflet_id = null
        container.innerHTML = ''
      }

      const latlngs = points.map((p) => [p.lat, p.lon] as [number, number])
      const map = L.map(container, { zoomControl: true })
      mapRef.current = map

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
      }).addTo(map)

      const polyline = L.polyline(latlngs, {
        color: '#6366f1',
        weight: 3,
        opacity: 0.85,
      }).addTo(map)

      // Start marker (green)
      L.circleMarker(latlngs[0], {
        radius: 6,
        fillColor: '#22c55e',
        color: '#fff',
        weight: 2,
        fillOpacity: 1,
      })
        .addTo(map)
        .bindTooltip('Start', { permanent: false, direction: 'top' })

      // End marker (red) — only if route doesn't close back on itself
      const last = latlngs[latlngs.length - 1]
      const distFromStart = Math.hypot(last[0] - latlngs[0][0], last[1] - latlngs[0][1])
      if (distFromStart > 0.001) {
        L.circleMarker(last, {
          radius: 6,
          fillColor: '#ef4444',
          color: '#fff',
          weight: 2,
          fillOpacity: 1,
        })
          .addTo(map)
          .bindTooltip('Finish', { permanent: false, direction: 'top' })
      }

      map.fitBounds(polyline.getBounds(), { padding: [16, 16] })
    })

    return () => {
      isMounted = false
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points])

  return (
    <div
      ref={containerRef}
      className="w-full rounded-lg overflow-hidden border border-border"
      style={{ height: 260 }}
    />
  )
}
