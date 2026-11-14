'use client'

import Link from 'next/link'
import { ArrowRight, Brain, CheckCircle2, Compass, Feather, Flame, Lock, LockOpen, Sparkles, Target, Trophy } from 'lucide-react'
import { Card, Pill, ProgressBar } from '@/components/ui-kit'
import { BADGES, type BadgeDef } from '@/lib/gamification'
import { challengesFor, nextChallengeInPath, pathProgress } from '@/lib/data'
import type { Challenge, PathDef } from '@/lib/types'
import { useStore } from '@/lib/store'
import { cn } from '@/lib/utils'

const BADGE_ICON = { sparkles: Sparkles, brain: Brain, target: Target, flame: Flame, 'lock-open': LockOpen, compass: Compass, trophy: Trophy, feather: Feather }
const BADGE_TONE = { coral: 'bg-coral text-plum', mint: 'bg-mint text-plum', lavender: 'bg-lavender text-white', plum: 'bg-plum text-coral' }

export function BadgeTile({ badge, earned, compact }: { badge: BadgeDef; earned: boolean; compact?: boolean }) {
  const Icon = BADGE_ICON[badge.icon]
  return (
    <div className={cn('flex items-center gap-3 rounded-2xl border border-border bg-card p-3', !earned && 'opacity-55')} title={badge.description}>
      <div className={cn('grid size-10 shrink-0 place-items-center rounded-xl', earned ? BADGE_TONE[badge.tone] : 'bg-ivory-deep text-muted-foreground')}>
        {earned ? <Icon className="size-5" /> : <Lock className="size-4" />}
      </div>
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-plum">{badge.name}</p>
        {!compact && <p className="text-xs text-muted-foreground">{badge.description}</p>}
      </div>
    </div>
  )
}

export function BadgeGrid({ compact }: { compact?: boolean }) {
  const { state } = useStore()
  return (
    <div className={cn('grid gap-3', compact ? 'sm:grid-cols-2' : 'sm:grid-cols-2 lg:grid-cols-4')}>
      {BADGES.map((b) => (
        <BadgeTile key={b.id} badge={b} earned={state.badges.includes(b.id)} compact={compact} />
      ))}
    </div>
  )
}

export function StatTile({ label, value, hint, icon: Icon, tone }: { label: string; value: string | number; hint?: string; icon: React.ComponentType<{ className?: string }>; tone: 'coral' | 'mint' | 'lavender' | 'plum' }) {
  const bg = { coral: 'bg-coral/20 text-coral-deep', mint: 'bg-mint text-plum', lavender: 'bg-lavender-soft text-plum', plum: 'bg-plum text-coral' }[tone]
  return (
    <Card className="flex items-center gap-4 p-4">
      <div className={cn('grid size-12 shrink-0 place-items-center rounded-2xl', bg)}>
        <Icon className="size-5" />
      </div>
      <div className="min-w-0">
        <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{label}</p>
        <p className="font-heading text-2xl font-semibold text-plum tabular-nums">{value}</p>
        {hint && <p className="truncate text-xs text-muted-foreground">{hint}</p>}
      </div>
    </Card>
  )
}

const ACCENT = { coral: 'bg-coral', mint: 'bg-mint', lavender: 'bg-lavender-soft' } as const
const ACCENT_BAR = { coral: 'coral', mint: 'mint', lavender: 'lavender' } as const

export function PathCard({ path }: { path: PathDef }) {
  const { state } = useStore()
  const p = pathProgress(path.id, state.completions)
  const next = nextChallengeInPath(path.id, state.completions)
  return (
    <Card className="flex flex-col gap-4 p-0 overflow-hidden">
      <div className={cn('flex items-start justify-between gap-3 p-5', ACCENT[path.accent])}>
        <div>
          <h3 className="font-heading text-2xl font-semibold text-plum">{path.name}</h3>
          <p className="text-sm text-plum/75">{path.fullName}</p>
        </div>
        <Pill tone="plum">{p.currentLevel.name}</Pill>
      </div>
      <div className="flex flex-1 flex-col gap-4 px-5 pb-5">
        <p className="text-sm text-pretty text-muted-foreground">{path.description}</p>
        <div>
          <div className="mb-2 flex justify-between text-xs text-muted-foreground">
            <span>
              {p.done} of {p.total} challenges
            </span>
            <span>{p.percent}%</span>
          </div>
          <ProgressBar value={p.percent} tone={ACCENT_BAR[path.accent]} />
        </div>
        <div className="mt-auto flex flex-wrap gap-2">
          <Link
            href={next ? `/practice/${next.id}` : `/paths/${path.id}`}
            className="inline-flex h-10 items-center gap-2 rounded-xl bg-plum px-4 text-sm font-semibold text-ivory transition hover:bg-plum-soft focus-visible:ring-3 focus-visible:ring-lavender/50 focus-visible:outline-none"
          >
            {p.done === 0 ? 'Start path' : next ? 'Continue' : 'Review'} <ArrowRight className="size-4" />
          </Link>
          <Link href={`/paths/${path.id}`} className="inline-flex h-10 items-center rounded-xl px-3 text-sm font-medium text-plum underline-offset-4 hover:underline">
            View roadmap
          </Link>
        </div>
      </div>
    </Card>
  )
}

const DIFF_TONE = { Easy: 'mint', Medium: 'lavender', Hard: 'coral' } as const

export function ChallengeRow({ challenge, locked }: { challenge: Challenge; locked?: boolean }) {
  const { state } = useStore()
  const done = state.completions[challenge.id]
  const body = (
    <div className={cn('flex items-center gap-4 rounded-2xl border border-border bg-card p-4 transition', locked ? 'opacity-60' : 'hover:border-lavender hover:shadow-sm')}>
      <div className={cn('grid size-10 shrink-0 place-items-center rounded-full', done ? 'bg-mint text-plum' : locked ? 'bg-ivory-deep text-muted-foreground' : 'bg-coral/20 text-coral-deep')}>
        {done ? <CheckCircle2 className="size-5" /> : locked ? <Lock className="size-4" /> : <ArrowRight className="size-4" />}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium text-plum">{challenge.title}</p>
        <p className="truncate text-xs text-muted-foreground">
          {challenge.topic} &middot; {challenge.kind === 'code' ? 'Code' : 'Concept'}
        </p>
      </div>
      <Pill tone={DIFF_TONE[challenge.difficulty]} className="hidden sm:inline-flex">
        {challenge.difficulty}
      </Pill>
      <span className="w-14 text-right text-sm font-semibold text-plum tabular-nums">{challenge.xp} XP</span>
    </div>
  )
  if (locked) return <div aria-disabled="true">{body}</div>
  return (
    <Link href={`/practice/${challenge.id}`} className="block rounded-2xl focus-visible:ring-3 focus-visible:ring-lavender/50 focus-visible:outline-none">
      {body}
    </Link>
  )
}

export function pathCount(pathId: PathDef['id']) {
  return challengesFor(pathId).length
}
