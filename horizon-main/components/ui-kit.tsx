import { cn } from '@/lib/utils'

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-3xl border border-border bg-card p-5 shadow-[0_1px_0_rgba(36,21,47,0.04)]', className)} {...props} />
}

export function ProgressBar({ value, className, tone = 'coral' }: { value: number; className?: string; tone?: 'coral' | 'mint' | 'lavender' | 'plum' }) {
  const fill = { coral: 'bg-coral', mint: 'bg-mint-deep', lavender: 'bg-lavender', plum: 'bg-plum' }[tone]
  return (
    <div className={cn('h-2 w-full overflow-hidden rounded-full bg-ivory-deep', className)} role="progressbar" aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100}>
      <div className={cn('h-full rounded-full transition-[width] duration-700', fill)} style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
    </div>
  )
}

export function Pill({ className, tone = 'neutral', ...props }: React.HTMLAttributes<HTMLSpanElement> & { tone?: 'neutral' | 'coral' | 'mint' | 'lavender' | 'plum' }) {
  const t = {
    neutral: 'bg-ivory-deep text-ink',
    coral: 'bg-coral/20 text-plum',
    mint: 'bg-mint text-plum',
    lavender: 'bg-lavender-soft text-plum',
    plum: 'bg-plum text-ivory',
  }[tone]
  return <span className={cn('inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium', t, className)} {...props} />
}

export function PageHeader({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description?: string; action?: React.ReactNode }) {
  return (
    <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="max-w-2xl">
        {eyebrow && <p className="mb-1 text-xs font-semibold tracking-widest text-coral-deep uppercase">{eyebrow}</p>}
        <h1 className="font-heading text-3xl font-semibold text-balance text-plum sm:text-4xl">{title}</h1>
        {description && <p className="mt-2 text-pretty text-muted-foreground">{description}</p>}
      </div>
      {action}
    </header>
  )
}

export const fieldClass =
  'h-11 w-full rounded-xl border border-input bg-card px-3.5 text-sm text-ink outline-none transition placeholder:text-muted-foreground/70 focus-visible:border-lavender focus-visible:ring-3 focus-visible:ring-lavender/30 disabled:opacity-60'

export const primaryBtn =
  'inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-coral px-5 text-sm font-semibold text-plum transition hover:bg-coral-deep focus-visible:ring-3 focus-visible:ring-coral/40 focus-visible:outline-none active:translate-y-px disabled:pointer-events-none disabled:opacity-50'

export const ghostBtn =
  'inline-flex h-11 items-center justify-center gap-2 rounded-xl border border-input bg-card px-5 text-sm font-medium text-ink transition hover:bg-ivory-deep focus-visible:ring-3 focus-visible:ring-lavender/30 focus-visible:outline-none active:translate-y-px disabled:pointer-events-none disabled:opacity-50'

export const darkBtn =
  'inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-plum px-5 text-sm font-semibold text-ivory transition hover:bg-plum-soft focus-visible:ring-3 focus-visible:ring-lavender/40 focus-visible:outline-none active:translate-y-px disabled:pointer-events-none disabled:opacity-50'
