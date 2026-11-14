'use client'

import { useEffect, useRef } from 'react'
import Link from 'next/link'
import { ArrowRight, Award, ChevronUp, LockOpen } from 'lucide-react'
import { ProgressBar } from '@/components/ui-kit'
import { nextChallengeInPath } from '@/lib/data'
import type { CompletionResult } from '@/lib/store'
import { useStore } from '@/lib/store'
import type { Challenge, ScoreSet } from '@/lib/types'

const ROWS: { key: keyof ScoreSet; label: string }[] = [
  { key: 'code', label: 'Code' },
  { key: 'reasoning', label: 'Reasoning' },
  { key: 'prediction', label: 'Prediction' },
  { key: 'concept', label: 'Concept' },
  { key: 'complexity', label: 'Complexity' },
]

export function ResultDialog({ challenge, result, scores, hintsUsed }: { challenge: Challenge; result: CompletionResult; scores: ScoreSet; hintsUsed: number }) {
  const { state } = useStore()
  const ref = useRef<HTMLHeadingElement>(null)
  useEffect(() => ref.current?.focus(), [])
  const next = nextChallengeInPath(challenge.pathId, state.completions)

  return (
    <div className="fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-plum/60 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="result-title">
      <div className="my-auto w-full max-w-lg space-y-6 rounded-3xl bg-card p-6 shadow-2xl sm:p-8">
        <div className="text-center">
          <p className="text-xs font-semibold tracking-widest text-coral-deep uppercase">{result.alreadyCompleted ? 'Practice round complete' : 'Challenge complete'}</p>
          <h2 id="result-title" ref={ref} tabIndex={-1} className="mt-1 font-heading text-3xl font-semibold text-balance text-plum outline-none">
            {result.total > 0 ? `+${result.total} XP` : 'Well practised'}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">{challenge.title}</p>
        </div>

        <div className="space-y-3">
          {ROWS.filter((r) => scores[r.key] !== null).map((r) => (
            <div key={r.key}>
              <div className="mb-1 flex justify-between text-sm">
                <span className="text-ink">{r.label}</span>
                <span className="tabular-nums text-muted-foreground">{scores[r.key]}%</span>
              </div>
              <ProgressBar value={scores[r.key] ?? 0} tone="lavender" />
            </div>
          ))}
          <p className="text-xs text-muted-foreground">
            Hints used: {hintsUsed}. {challenge.concept}
          </p>
        </div>

        {result.awards.length > 0 && (
          <ul className="space-y-1.5 rounded-2xl bg-ivory-deep/70 p-4 text-sm">
            {result.awards.map((a) => (
              <li key={a.reason} className="flex justify-between gap-3">
                <span className="text-ink">{a.reason}</span>
                <span className="font-semibold text-mint-deep tabular-nums">+{a.amount}</span>
              </li>
            ))}
          </ul>
        )}

        <div className="space-y-2">
          {result.levelUp && (
            <p className="flex items-center gap-2 rounded-xl bg-coral/15 px-4 py-2.5 text-sm font-medium text-plum">
              <ChevronUp className="size-4 text-coral-deep" /> Level {result.levelUp.to}: {result.levelUp.title}
            </p>
          )}
          {result.newBadges.map((b) => (
            <p key={b.id} className="flex items-center gap-2 rounded-xl bg-lavender-soft px-4 py-2.5 text-sm font-medium text-plum">
              <Award className="size-4" /> Badge earned: {b.name}
            </p>
          ))}
          {result.unlocked.map((u) => (
            <p key={u.pathName + u.levelName} className="flex items-center gap-2 rounded-xl bg-mint/40 px-4 py-2.5 text-sm font-medium text-plum">
              <LockOpen className="size-4" /> Unlocked {u.levelName} in {u.pathName}
            </p>
          ))}
        </div>

        <div className="flex flex-col gap-2 sm:flex-row">
          {next && next.id !== challenge.id && (
            <Link href={`/practice/${next.id}`} className="inline-flex h-11 flex-1 items-center justify-center gap-2 rounded-xl bg-plum px-5 text-sm font-semibold text-ivory hover:bg-plum-soft focus-visible:ring-3 focus-visible:ring-lavender/50 focus-visible:outline-none">
              Next: {next.title.length > 22 ? `${next.title.slice(0, 22)}...` : next.title} <ArrowRight className="size-4" />
            </Link>
          )}
          <Link href={`/paths/${challenge.pathId}`} className="inline-flex h-11 flex-1 items-center justify-center rounded-xl border border-border px-5 text-sm font-semibold text-plum hover:bg-ivory-deep focus-visible:ring-3 focus-visible:ring-lavender/50 focus-visible:outline-none">
            Back to path
          </Link>
        </div>
      </div>
    </div>
  )
}
