'use client'

import Link from 'next/link'
import { ChevronLeft, Lock } from 'lucide-react'
import { Page } from '@/components/app-shell'
import { ChallengeRow } from '@/components/dashboard/widgets'
import { Card, PageHeader, Pill, ProgressBar } from '@/components/ui-kit'
import { LEVELS, challengesFor, coveredTopics, getPath, isLevelUnlocked, pathProgress } from '@/lib/data'
import type { PathId } from '@/lib/types'
import { useStore } from '@/lib/store'
import { cn } from '@/lib/utils'

export function PathDetail({ pathId }: { pathId: PathId }) {
  const { state } = useStore()
  const path = getPath(pathId)!
  const progress = pathProgress(pathId, state.completions)
  const covered = coveredTopics(pathId)

  return (
    <Page>
      <Link href="/paths" className="-mb-4 inline-flex items-center gap-1 text-sm font-medium text-muted-foreground hover:text-plum">
        <ChevronLeft className="size-4" /> All paths
      </Link>
      <PageHeader eyebrow={path.fullName} title={path.name} description={path.description} />

      <Card className="grid gap-5 sm:grid-cols-[1fr_auto] sm:items-center">
        <div>
          <div className="mb-2 flex justify-between text-sm">
            <span className="font-medium text-plum">
              {progress.done} of {progress.total} challenges completed
            </span>
            <span className="text-muted-foreground">{progress.percent}%</span>
          </div>
          <ProgressBar value={progress.percent} tone={path.accent === 'coral' ? 'coral' : path.accent === 'mint' ? 'mint' : 'lavender'} />
        </div>
        <Pill tone="plum">Current: {progress.currentLevel.name}</Pill>
      </Card>

      <section aria-labelledby="topics-h" className="space-y-3">
        <h2 id="topics-h" className="font-heading text-xl font-semibold text-plum">
          Topic coverage
        </h2>
        <ul className="flex flex-wrap gap-2">
          {path.topics.map((t) => (
            <li key={t}>
              <Pill tone={covered.has(t) ? 'mint' : 'neutral'} className={cn(!covered.has(t) && 'text-muted-foreground')}>
                {t}
                {!covered.has(t) && <span className="text-[10px] opacity-70">soon</span>}
              </Pill>
            </li>
          ))}
        </ul>
      </section>

      <div className="space-y-8">
        {LEVELS.map((level, i) => {
          const unlocked = isLevelUnlocked(pathId, level.id, state.completions)
          const list = challengesFor(pathId, level.id)
          const done = list.filter((c) => state.completions[c.id]).length
          const prev = LEVELS[i - 1]
          return (
            <section key={level.id} aria-labelledby={`lvl-${level.id}`} className="space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <span className={cn('grid size-8 place-items-center rounded-full text-sm font-bold', unlocked ? 'bg-coral text-plum' : 'bg-ivory-deep text-muted-foreground')}>{unlocked ? i + 1 : <Lock className="size-3.5" />}</span>
                <div className="flex-1">
                  <h2 id={`lvl-${level.id}`} className="font-heading text-xl font-semibold text-plum">
                    {level.name}
                  </h2>
                  <p className="text-sm text-muted-foreground">{level.tagline}</p>
                </div>
                <span className="text-sm text-muted-foreground">
                  {done}/{list.length}
                </span>
              </div>
              {!unlocked && prev && (
                <p className="rounded-xl bg-ivory-deep px-4 py-3 text-sm text-muted-foreground">
                  Complete {prev.requiredToUnlockNext} challenges in {prev.name} to unlock this level.
                </p>
              )}
              <div className="space-y-2.5">
                {list.length ? list.map((c) => <ChallengeRow key={c.id} challenge={c} locked={!unlocked} />) : <p className="text-sm text-muted-foreground">More challenges are on the way.</p>}
              </div>
            </section>
          )
        })}
      </div>
    </Page>
  )
}
