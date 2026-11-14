'use client'

import Link from 'next/link'
import { ArrowRight, Flame, Star, Target, Trophy } from 'lucide-react'
import { Page } from '@/components/app-shell'
import { BadgeGrid, PathCard, StatTile } from '@/components/dashboard/widgets'
import { DoodleMentor } from '@/components/mentor/doodle-mentor'
import { Card, PageHeader } from '@/components/ui-kit'
import { CHALLENGES, PATHS, nextChallengeInPath } from '@/lib/data'
import { levelForXp } from '@/lib/gamification'
import { useStore } from '@/lib/store'

function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

export default function HomePage() {
  const { state, user } = useStore()
  const lvl = levelForXp(state.xp)
  const done = Object.keys(state.completions).length
  const lastId = Object.values(state.completions).sort((a, b) => b.completedAt.localeCompare(a.completedAt))[0]?.challengeId
  const lastPath = CHALLENGES.find((c) => c.id === lastId)?.pathId ?? 'dsa'
  const next = nextChallengeInPath(lastPath, state.completions) ?? PATHS.map((p) => nextChallengeInPath(p.id, state.completions)).find(Boolean) ?? null

  return (
    <Page>
      <PageHeader eyebrow={greeting()} title={`${user?.name.split(' ')[0]}, ready to think out loud?`} description="Your mentor will ask the questions. You bring the reasoning." />

      <section className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <Card className="paper-grain relative overflow-hidden bg-plum p-0 text-ivory">
          <div className="grid items-center gap-2 sm:grid-cols-[1fr_16rem]">
            <div className="space-y-5 p-6 sm:p-8">
              <p className="text-xs font-semibold tracking-widest text-coral uppercase">{done === 0 ? 'Your first conversation' : 'Continue learning'}</p>
              {next ? (
                <>
                  <h2 className="font-heading text-3xl leading-tight font-semibold text-balance">{next.title}</h2>
                  <p className="text-sm text-ivory/75">
                    {next.topic} &middot; {next.difficulty} &middot; {next.xp} XP
                  </p>
                  <Link href={`/practice/${next.id}`} className="inline-flex h-11 items-center gap-2 rounded-xl bg-coral px-5 text-sm font-semibold text-plum transition hover:bg-coral-deep focus-visible:ring-3 focus-visible:ring-lavender/60 focus-visible:outline-none">
                    {done === 0 ? 'Meet your mentor' : 'Resume challenge'} <ArrowRight className="size-4" />
                  </Link>
                </>
              ) : (
                <h2 className="font-heading text-3xl font-semibold">Every challenge is complete. Impressive.</h2>
              )}
            </div>
            <div className="mx-auto w-52 rounded-t-[2rem] bg-ivory px-3 pt-4 sm:mx-0 sm:mr-6 sm:self-end sm:w-60">
              <DoodleMentor state="idle" />
            </div>
          </div>
        </Card>

        <div className="grid grid-cols-2 gap-4 lg:grid-cols-1">
          <StatTile label="Level" value={lvl.level} hint={lvl.title} icon={Star} tone="plum" />
          <StatTile label="Streak" value={`${state.streak} day${state.streak === 1 ? '' : 's'}`} hint={state.streak ? 'Keep it alive today' : 'Solve one to start'} icon={Flame} tone="coral" />
          <StatTile label="XP" value={state.xp} hint={`${lvl.toNext} to next level`} icon={Trophy} tone="lavender" />
          <StatTile label="Completed" value={done} hint={`of ${CHALLENGES.length} challenges`} icon={Target} tone="mint" />
        </div>
      </section>

      <section aria-labelledby="paths-h" className="space-y-4">
        <div className="flex items-end justify-between">
          <h2 id="paths-h" className="font-heading text-2xl font-semibold text-plum">
            Your learning paths
          </h2>
          <Link href="/paths" className="text-sm font-medium text-plum underline underline-offset-4">
            See all
          </Link>
        </div>
        <div className="grid gap-5 md:grid-cols-3">
          {PATHS.map((p) => (
            <PathCard key={p.id} path={p} />
          ))}
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-[1fr_1.2fr]">
        <Card>
          <h2 className="font-heading text-xl font-semibold text-plum">Recent activity</h2>
          {state.activity.length === 0 ? (
            <p className="mt-3 text-sm text-muted-foreground">Nothing yet. Complete a challenge and your wins will show up here.</p>
          ) : (
            <ul className="mt-4 space-y-3">
              {state.activity.slice(0, 6).map((a) => (
                <li key={a.id} className="flex items-start gap-3 text-sm">
                  <span className="mt-1.5 size-2 shrink-0 rounded-full bg-coral" />
                  <span className="flex-1 text-ink">{a.text}</span>
                  <time className="shrink-0 text-xs text-muted-foreground" dateTime={a.at}>
                    {new Date(a.at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                  </time>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-heading text-xl font-semibold text-plum">Badges</h2>
            <span className="text-xs text-muted-foreground">{state.badges.length} earned</span>
          </div>
          <BadgeGrid compact />
        </Card>
      </section>
    </Page>
  )
}
