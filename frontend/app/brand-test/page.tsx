'use client'

import { PLATFORM_BRANDS, ROUTEPASS_BRAND, PlatformKey } from '@/lib/brand-registry'
import { BrandBox, BrandIcon, BrandBadge } from '@/components/brand-box'

export default function BrandTestPage() {
  const allBrands = [ROUTEPASS_BRAND, ...Object.values(PLATFORM_BRANDS)]

  return (
    <div className="min-h-screen bg-bg text-text-primary p-8 md:p-12 font-sans space-y-16">
      <header className="space-y-2">
        <h1 className="text-display font-display text-primary">RoutePass Brand Testing</h1>
        <p className="text-body-lg text-text-secondary">
          A visual playground to verify typography, colors, and the new SVG BrandBox system across various contexts.
        </p>
      </header>

      {/* ── Typography ── */}
      <section className="space-y-6">
        <h2 className="text-heading-lg border-b border-border pb-2">Typography & Wordmarks</h2>
        <div className="grid md:grid-cols-2 gap-8">
          <div className="p-6 rounded-xl border border-border bg-surface space-y-4">
            <h3 className="text-label text-text-secondary uppercase tracking-widest">UI Font (Inter)</h3>
            <div className="space-y-2">
              <p className="text-heading-xl">Heading XL</p>
              <p className="text-heading-lg">Heading LG</p>
              <p className="text-heading-md">Heading MD</p>
              <p className="text-body-lg">Body Large (16px, 1.6lh)</p>
              <p className="text-body">Body Regular (14px, 1.6lh)</p>
              <p className="text-body-sm text-text-secondary">Body Small (13px, 1.5lh)</p>
              <p className="text-caption text-text-disabled">Caption (12px)</p>
            </div>
          </div>

          <div className="p-6 rounded-xl border border-border bg-surface space-y-6">
            <h3 className="text-label text-text-secondary uppercase tracking-widest">Display Font (Outfit)</h3>
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <BrandIcon brand="routepass" size={40} />
                <span className="text-display font-display text-primary">RoutePass</span>
              </div>
              <div className="flex items-center gap-3">
                <BrandIcon brand="routepass" size={24} />
                <span className="text-heading-lg font-display text-text-primary">RoutePass</span>
              </div>
              <div className="flex items-center gap-2">
                <BrandIcon brand="routepass" size={16} />
                <span className="text-body font-semibold font-display text-text-secondary">RoutePass</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Brand Grid ── */}
      <section className="space-y-6">
        <h2 className="text-heading-lg border-b border-border pb-2">Brand Palette & Variants</h2>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {allBrands.map((brand) => (
            <div key={brand.id} className="p-6 rounded-xl border border-border bg-surface space-y-6">

              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-heading-md font-semibold flex items-center gap-2">
                    {brand.name}
                    {brand.id === 'routepass' && (
                      <span className="text-caption px-2 py-0.5 rounded-full bg-primary-light text-primary">Self</span>
                    )}
                  </h3>
                  <div className="flex items-center gap-2 mt-1">
                    <span
                      className="w-4 h-4 rounded-full"
                      style={{ backgroundColor: brand.colors.primary }}
                    />
                    <code className="text-mono text-text-secondary">{brand.colors.primary}</code>
                  </div>
                </div>

                {/* Simulated Hub Node Glow */}
                <div
                  className="w-16 h-16 rounded-full flex items-center justify-center relative"
                  style={{
                    border: `1.5px solid ${brand.colors.primary}`,
                    boxShadow: `0 0 20px ${brand.colors.primary}40`,
                    backgroundColor: '#1a1a1a'
                  }}
                >
                  <BrandIcon brand={brand} size={24} variant="regular" />
                </div>
              </div>

              <div className="grid grid-cols-4 gap-4 pt-4 border-t border-border">
                {/* Tinted Box (Connections page style) */}
                <div className="space-y-2 flex flex-col items-center text-center">
                  <span className="text-caption text-text-secondary">Tinted Box</span>
                  <BrandBox brand={brand} size={48} tinted={true} variant="regular" />
                </div>

                {/* White Variant */}
                <div className="space-y-2 flex flex-col items-center text-center">
                  <span className="text-caption text-text-secondary">Mono White</span>
                  <div className="w-12 h-12 bg-[#1a1a1a] rounded-lg border border-border flex items-center justify-center">
                    <BrandIcon brand={brand} size={24} variant="white" />
                  </div>
                </div>

                {/* Black Variant */}
                <div className="space-y-2 flex flex-col items-center text-center">
                  <span className="text-caption text-text-secondary">Mono Black</span>
                  <div className="w-12 h-12 bg-[#f0f0f0] rounded-lg border border-border flex items-center justify-center">
                    <BrandIcon brand={brand} size={24} variant="black" />
                  </div>
                </div>

                {/* Inactive Variant */}
                <div className="space-y-2 flex flex-col items-center text-center">
                  <span className="text-caption text-text-secondary">Inactive</span>
                  <BrandBox brand={brand} size={48} tinted={true} variant="inactive" />
                </div>
              </div>

              {/* Context Examples */}
              <div className="pt-4 border-t border-border space-y-3">
                <span className="text-label text-text-secondary uppercase">In Context</span>

                <div className="flex flex-wrap gap-4">
                  {/* Fake Connection Card */}
                  <div className="flex items-center gap-3 px-3 py-2 rounded-lg border border-border bg-surface-raised w-full max-w-[200px]">
                    <BrandBox brand={brand} size={32} />
                    <div className="flex flex-col min-w-0">
                      <span className="text-body-sm truncate">{brand.name}</span>
                      <span className="text-caption text-success flex items-center gap-1">
                        <div className="w-1.5 h-1.5 rounded-full bg-success" /> Connected
                      </span>
                    </div>
                  </div>

                  {/* Clickable Badge - Ghost with Colored Hover */}
                  <BrandBadge brand={brand} variant="ghost" />

                  {/* Clickable Badge - Colored Icon & Text */}
                  <BrandBadge brand={brand} variant="outline" />

                  {/* Clickable Badge - Filled Background */}
                  <BrandBadge brand={brand} variant="filled" />

                  {/* Fake Activity Row Meta */}
                  <div className="flex items-center gap-2">
                    <div className="flex items-center justify-center w-6 h-6">
                      <BrandIcon brand={brand} size={16} variant="regular" />
                    </div>
                    <span className="text-body-sm text-text-secondary">Synced 2m ago</span>
                  </div>
                </div>

                {/* Simulated connection line (from landing page) */}
                <div className="w-full h-8 mt-4 relative flex items-center">
                  <div className="w-full h-px bg-border absolute" />
                  <div
                    className="h-0.5 relative z-10 w-full opacity-60"
                    style={{
                      background: `linear-gradient(90deg, ${brand.colors.primary} 0%, transparent 100%)`
                    }}
                  />
                  <div
                    className="absolute left-10 w-2 h-2 rounded-full z-20 shadow-md"
                    style={{ backgroundColor: brand.colors.primary, boxShadow: `0 0 10px ${brand.colors.primary}` }}
                  />
                </div>
              </div>

            </div>
          ))}
        </div>
      </section>

    </div>
  )
}
