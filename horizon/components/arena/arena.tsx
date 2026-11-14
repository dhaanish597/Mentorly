'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { ArrowRight, Check, ChevronLeft } from 'lucide-react'
import { CodePanel } from '@/components/arena/code-panel'
import { MentorPanel, type ChatMessage } from '@/components/arena/mentor-panel'
import { ProblemPanel } from '@/components/arena/problem-panel'
import { ResultDialog } from '@/components/arena/result-dialog'
import { ComplexityPanel, McqPanel, PredictPanel } from '@/components/arena/stage-panels'
import type { MentorState } from '@/components/mentor/doodle-mentor'
import { primaryBtn } from '@/components/ui-kit'
import { useSpeech } from '@/hooks/use-speech'
import { STAGE_LABEL, demoJudge, judgeAnswer, mentorLines, stagesFor, type DemoResult, type Stage } from '@/lib/arena'
import { getChallenge } from '@/lib/data'
import { buildStarter } from '@/lib/starters'
import { useStore, type CompletionResult, type XpAward } from '@/lib/store'
import type { Language, ScoreSet } from '@/lib/types'
import { cn } from '@/lib/utils'

const uid = () => Math.random().toString(36).slice(2, 10)
const avg = (xs: number[]) => (xs.length ? Math.round(xs.reduce((a, b) => a + b, 0) / xs.length) : 0)

export function Arena({ challengeId }: { challengeId: string }) {
  const challenge = getChallenge(challengeId)!
  const c = challenge
  const { state, user, saveDraft, recordSubmission, completeChallenge, updateSettings } = useStore()
  const speech = useSpeech(state.settings)
  const stages = useMemo(() => stagesFor(c), [c])

  const [stage, setStage] = useState<Stage>('explain')
  const [tab, setTab] = useState<'problem' | 'work'>('problem')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [override, setOverride] = useState<MentorState | null>(null)
  const [draft, setDraft] = useState('')
  const [hints, setHints] = useState(0)
  const [explainRetry, setExplainRetry] = useState(false)
  const [reflectIdx, setReflectIdx] = useState(0)
  const [reflectRetry, setReflectRetry] = useState(false)
  const [stageDone, setStageDone] = useState(false)
  const [language, setLanguage] = useState<Language>(state.settings.language)
  const [code, setCode] = useState('')
  const [codeResult, setCodeResult] = useState<DemoResult | null>(null)
  const [failedSubmits, setFailedSubmits] = useState(0)
  const [final, setFinal] = useState<{ result: CompletionResult; scores: ScoreSet } | null>(null)

  const acc = useRef({ code: null as number | null, prediction: null as number | null, complexity: null as number | null, mcq: null as number | null, reasoning: [] as number[], concept: [] as number[] })
  const introduced = useRef(false)
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])
  const reflectPrompts = useMemo(() => [c.whyPrompt, c.alternativePrompt, c.edgePrompt].filter(Boolean) as string[], [c])

  useEffect(() => () => timers.current.forEach(clearTimeout), [])

  const later = (fn: () => void, ms: number) => {
    timers.current.push(setTimeout(fn, ms))
  }

  const say = useCallback(
    (text: string) => {
      setMessages((m) => [...m, { id: uid(), role: 'mentor', text }])
      speech.speak(text)
    },
    [speech],
  )

  useEffect(() => {
    if (introduced.current) return
    introduced.current = true
    say(mentorLines.intro(user?.name.split(' ')[0] ?? 'there', c))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const draftKey = `${c.id}:${language}`
  const starter = useMemo(() => (c.fn ? buildStarter(c.fn, language) : ''), [c.fn, language])
  useEffect(() => {
    setCode(state.drafts[draftKey] ?? starter)
    setCodeResult(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftKey])

  const flash = (s: MentorState, ms = 2400) => {
    setOverride(s)
    later(() => setOverride(null), ms)
  }

  function think(ms: number, then: () => void) {
    setOverride('thinking')
    later(() => {
      setOverride(null)
      then()
    }, ms)
  }

  function enterReflect() {
    setStage('reflect')
    setTab('problem')
    setStageDone(false)
    setReflectIdx(0)
    say(`One last thing. ${reflectPrompts[0]}`)
  }

  function advance(from: Stage) {
    const next = stages[stages.indexOf(from) + 1]
    setStageDone(false)
    if (!next) return
    if (next === 'reflect') return enterReflect()
    setStage(next)
    setTab('work')
    if (next === 'predict') say(c.fresh.code?.prompt ?? 'One more check. Try this new question without running anything.')
    if (next === 'complexity') say('Now think about cost. What are the time and space complexity of the solution you wrote?')
  }

  function onSend() {
    const text = draft.trim()
    if (!text) return
    speech.stopListening()
    setDraft('')
    setMessages((m) => [...m, { id: uid(), role: 'student', text }])
    if (stage === 'explain') {
      think(900, () => {
        const j = judgeAnswer(text, c)
        if (j.quality === 'thin' && !explainRetry) {
          setExplainRetry(true)
          return say(mentorLines.thin(c))
        }
        acc.current.reasoning.push(j.score)
        flash('encouraging')
        say(c.kind === 'code' ? mentorLines.affirmCode(j.hits) : mentorLines.affirmMcq)
        advance('explain')
      })
    } else if (stage === 'reflect') {
      think(900, () => {
        const j = judgeAnswer(text, c)
        if (j.quality === 'thin' && !reflectRetry) {
          setReflectRetry(true)
          return say(mentorLines.thinReflect)
        }
        setReflectRetry(false)
        ;(reflectIdx === 0 ? acc.current.reasoning : acc.current.concept).push(j.score)
        if (reflectIdx + 1 < reflectPrompts.length) {
          setReflectIdx(reflectIdx + 1)
          flash('encouraging', 1800)
          say(`${mentorLines.reflectAck(j.hits + reflectIdx)} ${reflectPrompts[reflectIdx + 1]}`)
        } else {
          finish()
        }
      })
    }
  }

  function finish() {
    const r = acc.current
    const reasoning = r.reasoning.length ? avg(r.reasoning) : 50
    const concept = c.kind === 'mcq' ? avg([r.mcq ?? 0, ...r.concept]) : r.concept.length ? avg(r.concept) : reasoning
    const scores: ScoreSet = { code: r.code, reasoning, prediction: r.prediction, concept, complexity: r.complexity }
    const primary = c.kind === 'code' ? (r.code ?? 0) : (r.mcq ?? 0)

    const awards: XpAward[] = [
      { amount: Math.round(c.xp * 0.5 * (primary / 100)), reason: c.kind === 'code' ? `Solved ${c.title}` : `Answered ${c.title}` },
      { amount: Math.round(c.xp * 0.25 * (reasoning / 100)), reason: 'Clear reasoning' },
    ]
    if (r.prediction === 100) awards.push({ amount: Math.round(c.xp * 0.15), reason: 'Correct prediction' })
    if (r.complexity !== null && r.complexity > 0) awards.push({ amount: Math.round(c.xp * 0.1 * (r.complexity / 100)), reason: 'Complexity analysis' })
    if (hints === 0) awards.push({ amount: 5, reason: 'No hints used' })

    flash('celebrating', 6000)
    say(mentorLines.finish)
    setStage('done')
    setFinal({ result: completeChallenge({ challengeId: c.id, scores, hintsUsed: hints, awards: awards.filter((a) => a.amount > 0) }), scores })
  }

  function runCode(submit: boolean) {
    const res = demoJudge(c, code, starter, language)
    setCodeResult(res)
    if (!submit) return
    recordSubmission({ challengeId: c.id, language, passed: res.passed, total: res.total, verdict: res.verdict, code })
    if (res.verdict === 'Accepted (demo)') {
      acc.current.code = 100
      setStageDone(true)
      flash('encouraging')
      say(mentorLines.codePass)
    } else {
      const n = failedSubmits + 1
      setFailedSubmits(n)
      acc.current.code = Math.round((res.passed / Math.max(res.total, 1)) * 100)
      think(700, () => say(mentorLines.codeFail(c, res.verdict === 'Not implemented' ? 'It looks like the solution is not written yet.' : `${res.passed} of ${res.total} checks passed.`)))
    }
  }

  function onHint() {
    if (hints >= c.hints.length) return say(mentorLines.noMoreHints)
    const h = c.hints[hints]
    setHints(hints + 1)
    flash('thinking', 1200)
    say(`${mentorLines.hintIntro(hints + 1)} ${h}`)
  }

  const answerEnabled = stage === 'explain' || stage === 'reflect'
  const mentorState: MentorState = override ?? (speech.listening ? 'listening' : speech.speaking ? 'speaking' : 'idle')
  const placeholder = stage === 'explain' ? 'Explain the problem and your approach in your own words...' : stage === 'reflect' ? 'Answer the mentor’s question...' : 'Complete this step in the workspace'
  const stageIdx = stages.indexOf(stage)

  const continueBtn = stageDone && stage !== 'reflect' && (
    <button type="button" onClick={() => advance(stage)} className={cn(primaryBtn, 'mt-4')}>
      Continue <ArrowRight className="size-4" />
    </button>
  )

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-5 sm:px-6 lg:h-[calc(100dvh-0px)] lg:py-5">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <Link href={`/paths/${c.pathId}`} className="inline-flex items-center gap-1 text-sm font-medium text-muted-foreground hover:text-plum">
          <ChevronLeft className="size-4" /> Path
        </Link>
        <h1 className="font-heading text-xl font-semibold text-balance text-plum sm:text-2xl">{c.title}</h1>
        <ol className="ml-auto flex items-center gap-1.5 text-xs" aria-label="Challenge steps">
          {stages.map((s, i) => (
            <li key={s} aria-current={s === stage ? 'step' : undefined} className={cn('flex items-center gap-1.5 rounded-full px-3 py-1.5 font-medium', i < stageIdx || stage === 'done' ? 'bg-mint/50 text-mint-deep' : s === stage ? 'bg-plum text-ivory' : 'bg-ivory-deep text-muted-foreground')}>
              {(i < stageIdx || stage === 'done') && <Check className="size-3" />}
              {STAGE_LABEL[s]}
            </li>
          ))}
        </ol>
      </header>

      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
        <div className="flex min-h-0 flex-col lg:h-full">
          <MentorPanel
            mentorState={mentorState}
            messages={messages}
            answerEnabled={answerEnabled && !final}
            placeholder={placeholder}
            draft={draft}
            onDraft={setDraft}
            onSend={onSend}
            listening={speech.listening}
            supportsStt={speech.supportsStt}
            micError={speech.micError}
            onToggleMic={() => {
              if (speech.listening) return speech.stopListening()
              const base = draft ? `${draft} ` : ''
              speech.startListening((t) => setDraft(base + t))
            }}
            autoSpeak={state.settings.autoSpeak}
            onToggleSpeak={() => {
              if (state.settings.autoSpeak) speech.cancel()
              updateSettings({ autoSpeak: !state.settings.autoSpeak })
            }}
            onHint={onHint}
            hintsLeft={Math.max(0, c.hints.length - hints)}
            speaking={speech.speaking}
          />
        </div>

        <section aria-label="Workspace" className="min-h-0 space-y-4 overflow-y-auto pb-6 lg:pr-1">
          <div role="tablist" aria-label="Workspace view" className="inline-flex rounded-full bg-ivory-deep p-1">
            {(['problem', 'work'] as const).map((t) => (
              <button key={t} role="tab" type="button" aria-selected={tab === t} onClick={() => setTab(t)} className={cn('rounded-full px-4 py-1.5 text-sm font-medium transition', tab === t ? 'bg-card text-plum shadow-sm' : 'text-muted-foreground hover:text-plum')}>
                {t === 'problem' ? 'Problem' : 'Workspace'}
              </button>
            ))}
          </div>

          {tab === 'problem' ? (
            <ProblemPanel challenge={c} />
          ) : (
            <div role="tabpanel">
              {stage === 'code' && (
                <>
                  <CodePanel
                    language={language}
                    onLanguage={setLanguage}
                    code={code}
                    onCode={(v) => {
                      setCode(v)
                      saveDraft(draftKey, v)
                    }}
                    onReset={() => {
                      setCode(starter)
                      saveDraft(draftKey, starter)
                      setCodeResult(null)
                    }}
                    onRun={() => runCode(false)}
                    onSubmit={() => runCode(true)}
                    result={codeResult}
                    submitted={stageDone}
                    disabled={stageDone}
                  />
                  {failedSubmits >= 2 && !stageDone && (
                    <button type="button" className={cn(primaryBtn, 'mt-4')} onClick={() => advance('code')}>
                      Move on with partial credit <ArrowRight className="size-4" />
                    </button>
                  )}
                  {continueBtn}
                </>
              )}
              {stage === 'concept' && c.mcq && (
                <>
                  <McqPanel
                    question={c.mcq}
                    title="Choose the best answer"
                    onResolved={(s) => {
                      acc.current.mcq = s
                      setStageDone(true)
                      flash(s >= 50 ? 'encouraging' : 'idle')
                      say(s === 100 ? 'Exactly right.' : s === 50 ? 'You got there on the second try. That is learning.' : 'Not this time. Read the explanation, it is worth a minute.')
                    }}
                  />
                  {continueBtn}
                </>
              )}
              {stage === 'predict' && (
                <>
                  {c.fresh.code ? (
                    <PredictPanel
                      fresh={c.fresh.code}
                      onResolved={(s) => {
                        acc.current.prediction = s
                        setStageDone(true)
                        flash(s > 0 ? 'encouraging' : 'idle')
                        say(s > 0 ? mentorLines.predictRight : mentorLines.predictWrong)
                      }}
                    />
                  ) : (
                    c.fresh.mcq && (
                      <McqPanel
                        question={c.fresh.mcq}
                        title="A new case for you"
                        onResolved={(s) => {
                          acc.current.prediction = s
                          setStageDone(true)
                          flash(s > 0 ? 'encouraging' : 'idle')
                          say(s === 100 ? mentorLines.predictRight : 'Not this time. Read the explanation and see what you would change.')
                        }}
                      />
                    )
                  )}
                  {continueBtn}
                </>
              )}
              {stage === 'complexity' && c.complexity && (
                <>
                  <ComplexityPanel
                    complexity={c.complexity}
                    onResolved={(s) => {
                      acc.current.complexity = s
                      setStageDone(true)
                      flash(s === 100 ? 'encouraging' : 'idle')
                      say(s === 100 ? mentorLines.complexityRight : mentorLines.complexityWrong(c.complexity!.note))
                    }}
                  />
                  {continueBtn}
                </>
              )}
              {(stage === 'explain' || stage === 'reflect' || stage === 'done') && (
                <p className="rounded-2xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
                  {stage === 'done' ? 'You have finished this challenge.' : 'This step happens in the conversation. Answer your mentor by voice or text.'}
                </p>
              )}
            </div>
          )}
        </section>
      </div>

      {final && <ResultDialog challenge={c} result={final.result} scores={final.scores} hintsUsed={hints} />}
    </div>
  )
}
