import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

// All variants and sizes defined here — never inline in pages.
// DESIGN.md §Button is the spec.

const buttonVariants = cva(
  // Base classes shared by every variant
  [
    'inline-flex items-center justify-center gap-2',
    'font-sans font-medium whitespace-nowrap',
    'transition-colors duration-150',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2',
    'disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none',
    'select-none',
  ],
  {
    variants: {
      variant: {
        // Primary — mint bg, dark text (high contrast on any bg)
        primary: [
          'bg-primary text-text-inverse font-semibold',
          'hover:bg-primary-hover',
          'shadow-sm',
        ],
        // Accent — alias for primary (same visual, semantic distinction)
        accent: [
          'bg-accent text-text-inverse font-semibold',
          'hover:bg-accent-hover',
          'shadow-sm',
        ],
        // Secondary — subtle bordered button on dark bg
        secondary: [
          'bg-surface-raised text-text-primary border border-border-strong',
          'hover:bg-surface hover:border-border-strong',
          'shadow-sm',
        ],
        // Secondary-dark — used for ghost-like CTAs on pure black sections
        'secondary-dark': [
          'bg-white/[0.06] text-text-primary border border-border-strong',
          'hover:bg-white/[0.1]',
        ],
        ghost: [
          'bg-transparent text-text-secondary',
          'hover:bg-primary-light hover:text-primary',
        ],
        // Ghost for hero sections with explicit dark bg override
        'ghost-dark': [
          'bg-transparent text-text-secondary',
          'hover:bg-white/[0.06] hover:text-text-primary',
        ],
        danger: [
          'bg-error text-text-inverse',
          'hover:bg-red-700',
          'shadow-sm',
        ],
        link: [
          'bg-transparent text-primary underline-offset-4',
          'hover:underline',
          'p-0 h-auto shadow-none',
        ],
      },
      size: {
        sm: 'h-9 px-4 text-body-sm rounded-md',
        md: 'h-10 px-5 text-body rounded-md',
        lg: 'h-11 px-6 text-body-lg rounded-md',
        icon: 'h-9 w-9 rounded-md',
      },
    },
    defaultVariants: {
      variant: 'primary',
      size: 'md',
    },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
  loading?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, loading, children, disabled, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button'

    return (
      <Comp
        className={cn(buttonVariants({ variant, size }), className)}
        ref={ref}
        disabled={disabled ?? loading}
        aria-busy={loading}
        {...props}
      >
        {loading ? (
          <>
            <LoadingSpinner />
            {children}
          </>
        ) : (
          children
        )}
      </Comp>
    )
  },
)
Button.displayName = 'Button'

function LoadingSpinner() {
  return (
    <svg
      className="animate-spin h-4 w-4"
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      aria-hidden
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  )
}

export { Button, buttonVariants }
