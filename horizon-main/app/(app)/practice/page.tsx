'use client'

import { useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Search, Shuffle } from 'lucide-react'
import { Page } from '@/components/app-shell'
import { ChallengeRow } from '@/components/dashboard/widgets'
import { PageHeader, darkBtn, fieldClass } from '@/components/ui-kit'
import { CHALLENGES, PATHS, isLevelUnlocked } from '@/lib/data'
import { useStore } from '@/lib/store'
import { cn } from '@/lib/utils'

const DIFFS = ['All', 'Easy', 'Medium', 'Hard'] as const

export default function PracticePage() {
  const { state } = useStore()
  const router = useRouter()
  const [path, setPath] = useState<string>('all')
  const [diff, setDiff] = useState<(typeof DIFFS)[number]>('All')
  const [q, setQ] = useState('')
  const [hideDone, setHideDone] = useState(false)

  const list = useMemo(
    () =>
      CHALLENGES.filter(
        (c) =>
          (path === 'all' || c.pathId === path) &&
          (diff === 'All' || c.difficulty === diff) &&
          (!hideDone || !state.completions[c.id]) &&
          `${c.title} ${c.topic}`.toLowerCase().includes(q.toLowerCase()),
      ),
    [path, diff, q, hideDone, state.completions],
  )

  const surprise = () => {
    const open = CHALLENGES.filter((c) => !state.completions[c.id] && isLevelUnlocked(c.pathId, c.level, state.completions))
    const pool = open.length ? open : CHALLENGES
    router.push(`/practice/${pool[Math.floor(Math.random() * pool.length)].id}`)
  }

  const chip = (active: boolean) =>
    cn('rounded-full border px-3.5 py-1.5 text-sm font-medium transition focus-visible:ring-3 focus-visible:ring-lavender/40 focus-visible:outline-none', active ? 'border-plum bg-plum text-ivory' : 'border-border bg-card text-ink hover:bg-ivory-deep')

  return (
    <Page>
      <PageHeader
        eyebrow="Practice arena"
        title="Pick a challenge and start the conversation"
        description="Every challenge begins with your explanation, not your code."
        action={
          <button type="button" onClick={surprise} className={darkBtn}>
            <Shuffle className="size-4" /> Surprise me
          </button>
        }
      />

      <div className="space-y-4">
        <div className="relative max-w-md">
          <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by title or topic" aria-label="Search challenges" className={`${fieldClass} pl-10`} />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className={chip(path === 'all')} onClick={() => setPath('all')}>
            All paths
          </button>
          {PATHS.map((p) => (
            <button key={p.id} type="button" className={chip(path === p.id)} onClick={() => setPath(p.id)}>
              {p.name}
            </button>
          ))}
          <span className="mx-2 hidden h-5 w-px bg-border sm:block" />
          {DIFFS.map((d) => (
            <button key={d} type="button" className={chip(diff === d)} onClick={() => setDiff(d)}>
              {d}
            </button>
          ))}
          <label className="ml-auto flex items-center gap-2 text-sm text-muted-foreground">
            <input type="checkbox" checked={hideDone} onChange={(e) => setHideDone(e.target.checked)} className="size-4 accent-coral" />
            Hide completed
          </label>
        </div>
      </div>

      <div className="space-y-2.5">
        {list.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-border p-10 text-center text-muted-foreground">No challenges match those filters.</p>
        ) : (
          list.map((c) => <ChallengeRow key={c.id} challenge={c} locked={!isLevelUnlocked(c.pathId, c.level, state.completions)} />)
        )}
      </div>
    </Page>
  )
}
