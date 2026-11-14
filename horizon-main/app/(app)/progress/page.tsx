'use client'

import { useMemo } from 'react'
import { Bar, BarChart, CartesianGrid, PolarAngleAxis, PolarGrid, Radar, RadarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Brain, Flame, Sparkles, Target, Trophy } from 'lucide-react'
import { Page } from '@/components/app-shell'
import { BadgeGrid, StatTile } from '@/components/dashboard/widgets'
import { Card, PageHeader, ProgressBar, ghostBtn } from '@/components/ui-kit'
import { CHALLENGES, PATHS, getChallenge, pathProgress } from '@/lib/data'
import { levelForXp } from '@/lib/gamification'
import { useStore } from '@/lib/store'
import { cn } from '@/lib/utils'

const avg = (xs: number[]) => (xs.length ? Math.round(xs.reduce((a, b) => a + b, 0) / xs.length) : 0)
const dayKey = (d: Date) => d.toISOString().slice(0, 10)

export default function ProgressPage() {
  const { state, seedSampleProgress, resetProgress } = useStore()
  const lvl = levelForXp(state.xp)
  const completions = Object.values(state.completions)

  const xpByDay = useMemo(() => {
    const map = new Map<string, number>()
    state.transactions.forEach((t) => map.set(t.at.slice(0, 10), (map.get(t.at.slice(0, 10)) ?? 0) + t.amount))
    return Array.from({ length: 14 }, (_, i) => {
      const d = new Date(Date.now() - (13 - i) * 86_400_000)
      return { day: d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }), xp: map.get(dayKey(d)) ?? 0 }
    })
  }, [state.transactions])

  const skills = useMemo(() => {
    const pick = (f: (c: (typeof completions)[number]) => number | null) => avg(completions.map(f).filter((n): n is number => n !== null))
    return [
      { skill: 'Code', score: pick((c) => c.scores.code) },
      { skill: 'Reasoning', score: pick((c) => c.scores.reasoning) },
      { skill: 'Prediction', score: pick((c) => c.scores.prediction) },
      { skill: 'Concepts', score: pick((c) => c.scores.concept) },
      { skill: 'Complexity', score: pick((c) => c.scores.complexity) },
    ]
  }, [completions])

  const review = useMemo(() => {
    const byTopic = new Map<string, number[]>()
    completions.forEach((c) => {
      const ch = getChallenge(c.challengeId)
      if (!ch) return
      const s = [c.scores.reasoning, c.scores.concept, c.scores.code, c.scores.prediction].filter((n): n is number => n !== null)
      byTopic.set(ch.topic, [...(byTopic.get(ch.topic) ?? []), avg(s)])
    })
    return [...byTopic.entries()].map(([topic, v]) => ({ topic, score: avg(v) })).sort((a, b) => a.score - b.score).slice(0, 3)
  }, [completions])

  const weeks = useMemo(() => {
    const active = new Set(state.activeDays)
    const start = new Date()
    start.setDate(start.getDate() - 7 * 12 + 1)
    start.setDate(start.getDate() - start.getDay())
    return Array.from({ length: 12 }, (_, w) =>
      Array.from({ length: 7 }, (_, d) => {
        const date = new Date(start)
        date.setDate(start.getDate() + w * 7 + d)
        return { key: dayKey(date), on: active.has(dayKey(date)), future: date > new Date() }
      }),
    )
  }, [state.activeDays])

  const empty = completions.length === 0

  return (
    <Page>
      <PageHeader
        eyebrow="My progress"
        title="See how your thinking is growing"
        description="XP rewards the quality of your reasoning, not just a passing test."
        action={
          empty ? (
            <button type="button" onClick={seedSampleProgress} className={ghostBtn}>
              <Sparkles className="size-4" /> Load sample progress
            </button>
          ) : (
            <button type="button" onClick={resetProgress} className={ghostBtn}>
              Reset progress
            </button>
          )
        }
      />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile label="Total XP" value={state.xp} hint={`Level ${lvl.level} · ${lvl.title}`} icon={Trophy} tone="plum" />
        <StatTile label="Streak" value={state.streak} hint="days in a row" icon={Flame} tone="coral" />
        <StatTile label="Solved" value={completions.length} hint={`of ${CHALLENGES.length}`} icon={Target} tone="mint" />
        <StatTile label="Avg reasoning" value={completions.length ? `${avg(completions.map((c) => c.scores.reasoning))}%` : '--'} hint="explanation quality" icon={Brain} tone="lavender" />
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <h2 className="font-heading text-xl font-semibold text-plum">XP over the last 14 days</h2>
          <div className="mt-4 h-64" role="img" aria-label="Bar chart of XP earned per day for the last 14 days">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={xpByDay} margin={{ top: 8, right: 4, left: -20, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="#eadfce" />
                <XAxis dataKey="day" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: '#6b5f72' }} interval={1} />
                <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: '#6b5f72' }} allowDecimals={false} />
                <Tooltip cursor={{ fill: '#f6ead9' }} contentStyle={{ borderRadius: 12, border: '1px solid #eadfce', background: '#fffdf9' }} />
                <Bar dataKey="xp" fill="#ff735c" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card>
          <h2 className="font-heading text-xl font-semibold text-plum">Skill balance</h2>
          <div className="mt-2 h-64" role="img" aria-label="Radar chart of average scores across code, reasoning, prediction, concepts and complexity">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={skills} outerRadius="72%">
                <PolarGrid stroke="#eadfce" />
                <PolarAngleAxis dataKey="skill" tick={{ fontSize: 12, fill: '#29232d' }} />
                <Radar dataKey="score" stroke="#8c78b8" fill="#8c78b8" fillOpacity={0.35} />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <h2 className="font-heading text-xl font-semibold text-plum">Learning paths</h2>
          <div className="mt-4 space-y-5">
            {PATHS.map((p) => {
              const pr = pathProgress(p.id, state.completions)
              return (
                <div key={p.id}>
                  <div className="mb-1.5 flex justify-between text-sm">
                    <span className="font-medium text-plum">{p.name}</span>
                    <span className="text-muted-foreground">
                      {pr.done}/{pr.total} &middot; {pr.currentLevel.name}
                    </span>
                  </div>
                  <ProgressBar value={pr.percent} tone={p.accent === 'coral' ? 'coral' : p.accent === 'mint' ? 'mint' : 'lavender'} />
                </div>
              )
            })}
          </div>
        </Card>

        <Card>
          <h2 className="font-heading text-xl font-semibold text-plum">Worth reviewing</h2>
          {review.length === 0 ? (
            <p className="mt-3 text-sm text-muted-foreground">Finish a few challenges and your mentor will point out topics to revisit.</p>
          ) : (
            <ul className="mt-4 space-y-3">
              {review.map((r) => (
                <li key={r.topic} className="flex items-center justify-between rounded-xl bg-ivory-deep px-3.5 py-2.5 text-sm">
                  <span className="font-medium text-plum">{r.topic}</span>
                  <span className="text-muted-foreground">{r.score}%</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card>
        <h2 className="font-heading text-xl font-semibold text-plum">Consistency</h2>
        <p className="text-sm text-muted-foreground">Last 12 weeks. Each square is a day you practised.</p>
        <div className="mt-4 flex gap-1.5 overflow-x-auto pb-1" role="img" aria-label={`${state.activeDays.length} active days in the last 12 weeks`}>
          {weeks.map((week, i) => (
            <div key={i} className="flex flex-col gap-1.5">
              {week.map((d) => (
                <span key={d.key} title={d.key} className={cn('size-4 rounded-[5px]', d.future ? 'bg-transparent' : d.on ? 'bg-coral' : 'bg-ivory-deep')} />
              ))}
            </div>
          ))}
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-[1fr_1.3fr]">
        <Card>
          <h2 className="font-heading text-xl font-semibold text-plum">XP history</h2>
          {state.transactions.length === 0 ? (
            <p className="mt-3 text-sm text-muted-foreground">Your XP rewards will be listed here with the reason for each.</p>
          ) : (
            <ul className="mt-4 max-h-80 divide-y divide-border overflow-y-auto pr-1">
              {state.transactions.slice(0, 30).map((t) => (
                <li key={t.id} className="flex items-center justify-between gap-3 py-2.5 text-sm">
                  <span className="min-w-0 flex-1 truncate text-ink">{t.reason}</span>
                  <span className="font-semibold text-mint-deep tabular-nums">+{t.amount}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card>
          <h2 className="mb-4 font-heading text-xl font-semibold text-plum">Badges</h2>
          <BadgeGrid compact />
        </Card>
      </div>
    </Page>
  )
}
