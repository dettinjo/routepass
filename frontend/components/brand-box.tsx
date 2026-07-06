import Image from 'next/image'
import { getBrand, PlatformKey, BrandConfig } from '@/lib/brand-registry'
import { cn } from '@/lib/utils'

export type BrandVariant = 'regular' | 'white' | 'black' | 'inactive'

interface BrandIconProps {
  brand: PlatformKey | 'routepass' | BrandConfig
  variant?: BrandVariant
  size?: number
  className?: string
}

export function BrandIcon({ brand, variant = 'regular', size = 24, className }: BrandIconProps) {
  const config = typeof brand === 'string' ? getBrand(brand) : brand
  // Inactive uses the white icon by default as it's cleaner to grey out
  const src = config.assets[variant === 'inactive' ? 'white' : variant]

  return (
    <Image
      src={src}
      width={size}
      height={size}
      alt={`${config.name} icon`}
      className={cn(variant === 'inactive' && 'opacity-30', className)}
      aria-hidden="true"
    />
  )
}

interface BrandBoxProps extends BrandIconProps {
  tinted?: boolean
}

export function BrandBox({ brand, variant = 'regular', size = 40, tinted = true, className }: BrandBoxProps) {
  const config = typeof brand === 'string' ? getBrand(brand) : brand

  // Use a neutral background if inactive, otherwise the primary color tint
  const bgColor = variant === 'inactive'
    ? 'rgba(255, 255, 255, 0.04)'
    : tinted ? `${config.colors.primary}18` : 'transparent'

  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: Math.round(size * 0.14),
        backgroundColor: bgColor,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
      }}
      className={cn(className)}
    >
      <BrandIcon
        brand={config}
        variant={variant}
        size={Math.round(size * 0.58)}
      />
    </div>
  )
}

export type BadgeVariant = 'ghost' | 'outline' | 'filled'

interface BrandBadgeProps {
  brand: PlatformKey | 'routepass' | BrandConfig
  variant?: BadgeVariant
  className?: string
  onClick?: () => void
  href?: string
  children?: React.ReactNode
}

export function BrandBadge({ brand, variant = 'ghost', className, onClick, href, children }: BrandBadgeProps) {
  const config = typeof brand === 'string' ? getBrand(brand) : brand
  const linkHref = href || config.url

  // If there's a link (and it's not a dummy '#'), render as an anchor tag, otherwise as a button
  const isLink = linkHref && linkHref !== '#'
  const Wrapper = isLink ? 'a' : 'button'
  const wrapperProps = isLink
    ? { href: linkHref, target: '_blank', rel: 'noopener noreferrer' }
    : { onClick, type: 'button' as const }

  if (variant === 'ghost') {
    return (
      <Wrapper
        {...wrapperProps}
        className={cn("group flex items-center gap-2 px-3 py-2 rounded-lg border border-border bg-surface hover:bg-[var(--hover-bg)] hover:border-[var(--hover-color)] transition-all duration-200 cursor-pointer", className)}
        style={{
          '--hover-color': config.colors.primary,
          '--hover-bg': `${config.colors.primary}10`,
        } as React.CSSProperties}
      >
        <div className="flex group-hover:hidden opacity-70">
          <BrandIcon brand={config} size={16} variant="white" />
        </div>
        <div className="hidden group-hover:flex">
          <BrandIcon brand={config} size={16} variant="regular" />
        </div>
        <span className="text-body-sm font-medium text-text-secondary group-hover:text-[var(--hover-color)] transition-colors">
          {config.name}
        </span>
        {children}
      </Wrapper>
    )
  }

  if (variant === 'outline') {
    return (
      <Wrapper
        {...wrapperProps}
        className={cn("group flex items-center gap-2 px-3 py-2 rounded-lg border bg-surface hover:bg-[var(--hover-bg)] transition-all duration-200 cursor-pointer", className)}
        style={{
          '--brand-color': config.colors.primary,
          '--hover-bg': `${config.colors.primary}10`,
          borderColor: `${config.colors.primary}40`
        } as React.CSSProperties}
      >
        <BrandIcon brand={config} size={16} variant="regular" />
        <span className="text-body-sm font-semibold transition-colors" style={{ color: 'var(--brand-color)' }}>
          {config.name}
        </span>
        {children}
      </Wrapper>
    )
  }

  // filled
  return (
    <Wrapper
      {...wrapperProps}
      className={cn("group flex items-center gap-2 px-3 py-2 rounded-lg transition-all duration-200 hover:opacity-90 cursor-pointer", className)}
      style={{ backgroundColor: config.colors.primary }}
    >
      <BrandIcon brand={config} size={16} variant="white" />
      <span className="text-body-sm font-semibold text-white">
        {config.name}
      </span>
      {children}
    </Wrapper>
  )
}
