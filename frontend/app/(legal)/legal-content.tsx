export function LegalTitle({ children, updated }: { children: React.ReactNode; updated: string }) {
  return (
    <div className="mb-10">
      <h1 className="text-3xl font-bold font-display tracking-tight text-text-primary mb-2">{children}</h1>
      <p className="text-sm text-text-secondary">Last updated: {updated}</p>
    </div>
  )
}

export function H2({ children }: { children: React.ReactNode }) {
  return <h2 className="text-xl font-semibold text-text-primary mt-10 mb-3">{children}</h2>
}

export function P({ children }: { children: React.ReactNode }) {
  return <p className="text-sm leading-relaxed text-text-secondary mb-4">{children}</p>
}

export function Ul({ children }: { children: React.ReactNode }) {
  return <ul className="list-disc pl-5 space-y-2 text-sm leading-relaxed text-text-secondary mb-4">{children}</ul>
}

export function A({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} className="text-primary hover:text-primary-hover underline underline-offset-2">
      {children}
    </a>
  )
}
