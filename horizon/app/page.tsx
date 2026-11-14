'use client'

import Link from 'next/link'
import { ArrowRight, Brain, Code2, Flame, MessageCircleQuestion, Mic, Trophy } from 'lucide-react'
import { BrandLogo } from '@/components/brand-logo'
import { DoodleMentor } from '@/components/mentor/doodle-mentor'
import { PATHS } from '@/lib/data'
import { useStore } from '@/lib/store'

const STEPS = [
  { icon: Mic, title: 'Explain it out loud', body: 'Before touching code, tell your mentor what the problem asks and how you would attack it. Speak or type.' },
  { icon: Code2, title: 'Build and predict', body: 'Write the solution, then predict the output of an input you have never seen. No copying, no guessing.' },
  { icon: MessageCircleQuestion, title: 'Defend your thinking', body: 'Your mentor asks why, what else, and what breaks. The questions are the lesson.' },
]

export default function LandingPage() {
  const { user, ready } = useStore()
  const signedIn = ready && !!user

  return (
    <div className="min-h-dvh bg-background">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-5 sm:px-8">
        <BrandLogo />
        <nav className="flex items-center gap-2 sm:gap-3" aria-label="Account">
          {signedIn ? (
            <Link href="/home" className="inline-flex h-10 items-center rounded-xl bg-plum px-4 text-sm font-semibold text-ivory hover:bg-plum-soft">
              Open dashboard
            </Link>
          ) : (
            <>
              <Link href="/auth/login" className="inline-flex h-10 items-center rounded-xl px-4 text-sm font-semibold text-plum hover:bg-ivory-deep">
                Log in
              </Link>
              <Link href="/auth/sign-up" className="inline-flex h-10 items-center rounded-xl bg-plum px-4 text-sm font-semibold text-ivory hover:bg-plum-soft">
                Start free
              </Link>
            </>
          )}
        </nav>
      </header>

      <main>
        <section className="mx-auto grid max-w-6xl items-center gap-10 px-4 pt-8 pb-20 sm:px-8 lg:grid-cols-[1.15fr_1fr] lg:pt-16">
          <div className="space-y-7">
            <p className="inline-flex rounded-full bg-lavender-soft px-3.5 py-1.5 text-xs font-semibold tracking-wide text-plum">A conversational coding mentor</p>
            <h1 className="font-heading text-5xl leading-[1.05] font-semibold tracking-tight text-balance text-plum sm:text-6xl">
              It never gives the answer. It asks <span className="text-coral-deep">you</span> questions.
            </h1>
            <p className="max-w-xl text-lg leading-relaxed text-pretty text-muted-foreground">
              Mentorly teaches data structures, aptitude and verbal reasoning the way a great interviewer does: you explain, you build, you defend. Every challenge is a conversation, and you earn XP for how well you think.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <Link href={signedIn ? '/home' : '/auth/sign-up'} className="inline-flex h-12 items-center gap-2 rounded-xl bg-coral px-6 text-base font-semibold text-plum transition hover:bg-coral-deep focus-visible:ring-3 focus-visible:ring-lavender/50 focus-visible:outline-none">
                {signedIn ? 'Continue learning' : 'Meet your mentor'} <ArrowRight className="size-4" />
              </Link>
              <Link href="#how" className="inline-flex h-12 items-center rounded-xl border border-border px-6 text-base font-semibold text-plum hover:bg-ivory-deep">
                How it works
              </Link>
            </div>
          </div>

          <div className="paper-grain relative mx-auto w-full max-w-md rounded-[2rem] bg-ivory-deep p-6">
            <div className="mx-auto w-64 sm:w-72">
              <DoodleMentor state="thinking" />
            </div>
            <figure className="mt-2 text-center">
              <blockquote className="font-heading text-xl text-balance text-plum italic">&ldquo;Before you write a line, what would you check first?&rdquo;</blockquote>
              <figcaption className="mt-2 text-xs tracking-wide text-muted-foreground uppercase">Your mentor, every challenge</figcaption>
            </figure>
          </div>
        </section>

        <section id="how" className="bg-plum py-20 text-ivory">
          <div className="mx-auto max-w-6xl space-y-12 px-4 sm:px-8">
            <div className="max-w-2xl space-y-3">
              <h2 className="font-heading text-4xl font-semibold text-balance">Three moves, every time</h2>
              <p className="text-ivory/70">The order is deliberate. Understanding comes first, so the code you write is yours.</p>
            </div>
            <ol className="grid gap-5 md:grid-cols-3">
              {STEPS.map((s, i) => (
                <li key={s.title} className="rounded-3xl border border-plum-line bg-plum-soft p-6">
                  <span className="grid size-11 place-items-center rounded-xl bg-coral text-plum">
                    <s.icon className="size-5" />
                  </span>
                  <p className="mt-5 text-xs font-semibold tracking-widest text-coral uppercase">Step {i + 1}</p>
                  <h3 className="mt-1 font-heading text-xl font-semibold">{s.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-ivory/70">{s.body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="mx-auto max-w-6xl space-y-10 px-4 py-20 sm:px-8">
          <div className="max-w-2xl space-y-3">
            <h2 className="font-heading text-4xl font-semibold text-balance text-plum">Three paths, three levels each</h2>
            <p className="text-muted-foreground">Finish two challenges in a level to unlock the next one.</p>
          </div>
          <div className="grid gap-5 md:grid-cols-3">
            {PATHS.map((p) => (
              <article key={p.id} className="rounded-3xl border border-border bg-card p-6">
                <h3 className="font-heading text-2xl font-semibold text-plum">{p.name}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{p.fullName}</p>
                <p className="mt-4 text-sm leading-relaxed text-ink">{p.description}</p>
                <ul className="mt-5 flex flex-wrap gap-1.5">
                  {p.topics.slice(0, 5).map((t) => (
                    <li key={t} className="rounded-full bg-ivory-deep px-2.5 py-1 text-xs text-plum">
                      {t}
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </section>

        <section className="bg-ivory-deep py-20">
          <div className="mx-auto grid max-w-6xl items-center gap-10 px-4 sm:px-8 lg:grid-cols-2">
            <div className="space-y-4">
              <h2 className="font-heading text-4xl font-semibold text-balance text-plum">Rewarded for reasoning, not just results</h2>
              <p className="text-muted-foreground">XP comes from clear explanations, correct predictions and honest complexity analysis. Hints are free, but a hint-free solve earns a bonus.</p>
            </div>
            <ul className="grid grid-cols-3 gap-4">
              {[
                { icon: Flame, label: 'Daily streaks' },
                { icon: Trophy, label: 'Levels and badges' },
                { icon: Brain, label: 'Skill insights' },
              ].map((f) => (
                <li key={f.label} className="flex flex-col items-center gap-3 rounded-3xl bg-card p-5 text-center">
                  <span className="grid size-12 place-items-center rounded-full bg-lavender-soft text-plum">
                    <f.icon className="size-5" />
                  </span>
                  <span className="text-sm font-medium text-plum">{f.label}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </main>

      <footer className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 py-10 text-sm text-muted-foreground sm:px-8">
        <BrandLogo />
        <p>Demo mode: accounts and progress are stored in this browser.</p>
      </footer>
    </div>
  )
}
