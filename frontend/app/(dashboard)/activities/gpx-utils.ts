/** Pure GPX parsing utilities — no DOM map rendering, safe to import anywhere. */

export interface LatLon {
  lat: number
  lon: number
}

/** Parse GPX XML bytes/string and return an ordered array of {lat, lon} points. */
export function parseGpxPoints(gpxText: string): LatLon[] {
  const parser = new DOMParser()
  const doc = parser.parseFromString(gpxText, 'application/xml')
  const trkpts = Array.from(doc.querySelectorAll('trkpt'))
  return trkpts
    .map((pt) => {
      const lat = parseFloat(pt.getAttribute('lat') ?? '')
      const lon = parseFloat(pt.getAttribute('lon') ?? '')
      return Number.isFinite(lat) && Number.isFinite(lon) ? { lat, lon } : null
    })
    .filter((p): p is LatLon => p !== null)
}
