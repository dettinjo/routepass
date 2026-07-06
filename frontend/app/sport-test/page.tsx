'use client'

import { SPORT_LABELS } from '@/lib/utils'
import { SportIcon } from '@/components/sport-icon'

export default function SportTestPage() {
  // Group keys by their display label (category)
  const categoriesMap: Record<string, { komootKeys: string[]; stravaKeys: string[] }> = {}

  Object.entries(SPORT_LABELS).forEach(([key, label]) => {
    if (!categoriesMap[label]) {
      categoriesMap[label] = { komootKeys: [], stravaKeys: [] }
    }

    // Strava & Intervals.icu keys are PascalCase. Komoot & Runalyze keys are lowercase/snake_case.
    // A simple heuristic: if the first character is uppercase, it's Strava/Intervals.
    const isStrava = key.charAt(0) === key.charAt(0).toUpperCase()
    if (isStrava) {
      categoriesMap[label].stravaKeys.push(key)
    } else {
      categoriesMap[label].komootKeys.push(key)
    }
  })

  // Convert map to array and sort alphabetically by category name
  const categories = Object.entries(categoriesMap)
    .map(([label, data]) => ({ label, ...data }))
    .sort((a, b) => a.label.localeCompare(b.label))

  return (
    <div className="min-h-screen bg-bg text-text-primary p-8 md:p-12 font-sans space-y-12">
      <header className="space-y-2">
        <h1 className="text-display font-display text-primary">Sport Categories Overview</h1>
        <p className="text-body-lg text-text-secondary">
          A visual overview of how internal platform typings (Strava, Komoot, Intervals.icu, Runalyze) map to RoutePass sport categories and icons.
        </p>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        {categories.map(({ label, komootKeys, stravaKeys }) => {
          // Use the first key available to get the icon (SportIcon doesn't care which platform key it is, as long as it maps)
          const sampleKey = komootKeys[0] || stravaKeys[0]

          return (
            <div key={label} className="p-6 rounded-xl border border-border bg-surface space-y-6">

              <div className="flex items-center gap-4 border-b border-border pb-4">
                <div
                  className="w-14 h-14 rounded-full flex items-center justify-center relative bg-surface-raised"
                  style={{ border: '1px solid var(--border)', color: 'var(--primary)' }}
                >
                  <SportIcon sportType={sampleKey} size={30} />
                </div>
                <div>
                  <h3 className="text-heading-md font-semibold text-text-primary">{label}</h3>
                  <p className="text-caption text-text-disabled mt-0.5">
                    {komootKeys.length + stravaKeys.length} mapping(s)
                  </p>
                </div>
              </div>

              <div className="space-y-4">
                {/* Komoot & Runalyze mappings */}
                <div className="space-y-2">
                  <h4 className="text-label text-text-secondary uppercase flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#6AA127' }} />
                    Komoot / Runalyze
                  </h4>
                  {komootKeys.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {komootKeys.map((k) => (
                        <span key={k} className="px-2 py-1 rounded bg-surface-raised border border-border text-mono text-caption text-text-secondary">
                          {k}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="text-caption text-text-disabled italic">No mapping</p>
                  )}
                </div>

                {/* Strava & Intervals mappings */}
                <div className="space-y-2">
                  <h4 className="text-label text-text-secondary uppercase flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#FC4C02' }} />
                    Strava / Intervals.icu
                  </h4>
                  {stravaKeys.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {stravaKeys.map((k) => (
                        <span key={k} className="px-2 py-1 rounded bg-surface-raised border border-border text-mono text-caption text-text-secondary">
                          {k}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="text-caption text-text-disabled italic">No mapping</p>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
