'use client'

import { useState } from 'react'
import { CheckCircle2, XCircle } from 'lucide-react'
import { Card, fieldClass, primaryBtn } from '@/components/ui-kit'
import { complexityOptions, normalizeAnswer, sameComplexity } from '@/lib/arena'
import type { Complexity, FreshCode, McqQuestion } from '@/lib/types'
import { cn } from '@/lib/utils'

export function McqPanel({ question, title, onResolved }: { question: McqQuestion; title: string; onResolved: (score: number) => void }) {
  const [picked, setPicked] = useState<number | null>(null)
  const [attempts, setAttempts] = useState(0)
  const [resolved, setResolved] = useState(false)
  const correct = picked === question.answerIndex

  function check() {
    if (picked === null) return
    const n = attempts + 1
    setAttempts(n)
    if (picked === question.answerIndex) {
      setResolved(true)
      onResolved(n === 1 ? 100 : 50)
    } else if (n >= 2) {
      setResolved(true)
      onResolved(0)
    }
  }

  return (
    <Card className="space-y-5">
      <div>
        <p className="text-xs font-semibold tracking-wide text-coral-deep uppercase">{title}</p>
        <h3 className="mt-1 font-heading text-xl font-semibold text-balance text-plum">{question.question}</h3>
      </div>
      <fieldset className="space-y-2.5" disabled={resolved}>
        <legend className="sr-only">Choose one answer</legend>
        {question.options.map((o, i) => (
          <label
            key={i}
            className={cn(
              'flex cursor-pointer items-start gap-3 rounded-xl border p-3.5 text-sm transition has-focus-visible:ring-3 has-focus-visible:ring-lavender/40',
              picked === i ? 'border-plum bg-lavender-soft/50' : 'border-border hover:bg-ivory-deep/60',
              resolved && i === question.answerIndex && 'border-mint-deep bg-mint/40',
              resolved && picked === i && !correct && 'border-destructive bg-destructive/5',
            )}
          >
            <input type="radio" name="mcq" className="mt-0.5 size-4 accent-plum" checked={picked === i} onChange={() => setPicked(i)} />
            <span className="text-ink">{o}</span>
          </label>
        ))}
      </fieldset>
      {!resolved && attempts === 1 && !correct && (
        <p role="alert" className="text-sm text-destructive">
          Not quite. Re-read the question and try once more.
        </p>
      )}
      {resolved ? (
        <div className={cn('flex gap-3 rounded-xl p-4 text-sm', correct ? 'bg-mint/40' : 'bg-ivory-deep')} role="status">
          {correct ? <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-mint-deep" /> : <XCircle className="mt-0.5 size-5 shrink-0 text-destructive" />}
          <p className="text-ink">{question.explanation}</p>
        </div>
      ) : (
        <button type="button" onClick={check} disabled={picked === null} className={primaryBtn}>
          Check answer
        </button>
      )}
    </Card>
  )
}

export function PredictPanel({ fresh, onResolved }: { fresh: FreshCode; onResolved: (score: number, attempts: number) => void }) {
  const [value, setValue] = useState('')
  const [attempts, setAttempts] = useState(0)
  const [state, setState] = useState<'open' | 'right' | 'revealed'>('open')

  function check() {
    const n = attempts + 1
    setAttempts(n)
    if (normalizeAnswer(value) === normalizeAnswer(fresh.expected)) {
      setState('right')
      onResolved(n === 1 ? 100 : 50, n)
    } else if (n >= 2) {
      setState('revealed')
      onResolved(0, n)
    }
  }

  return (
    <Card className="space-y-5">
      <div>
        <p className="text-xs font-semibold tracking-wide text-coral-deep uppercase">Predict the output</p>
        <p className="mt-1 text-ink">{fresh.prompt}</p>
      </div>
      <pre className="overflow-x-auto rounded-xl bg-plum px-4 py-3 font-mono text-sm text-ivory">{fresh.input}</pre>
      <div className="space-y-1.5">
        <label htmlFor="predict" className="text-sm font-medium text-plum">
          Your prediction
        </label>
        <input id="predict" value={value} onChange={(e) => setValue(e.target.value)} disabled={state !== 'open'} onKeyDown={(e) => e.key === 'Enter' && !e.nativeEvent.isComposing && value.trim() && state === 'open' && check()} className={cn(fieldClass, 'font-mono')} />
      </div>
      {state === 'open' && attempts === 1 && (
        <p role="alert" className="text-sm text-destructive">
          Not quite. Trace the input step by step, then try again.
        </p>
      )}
      {state === 'right' && (
        <p role="status" className="flex items-center gap-2 text-sm font-medium text-mint-deep">
          <CheckCircle2 className="size-4" /> Correct.
        </p>
      )}
      {state === 'revealed' && (
        <p role="status" className="rounded-xl bg-ivory-deep px-4 py-3 text-sm text-ink">
          The answer was <span className="font-mono font-semibold">{fresh.expected}</span>. Trace it again later and see where your prediction diverged.
        </p>
      )}
      {state === 'open' && (
        <button type="button" onClick={check} disabled={!value.trim()} className={primaryBtn}>
          Check prediction
        </button>
      )}
    </Card>
  )
}

export function ComplexityPanel({ complexity, onResolved }: { complexity: Complexity; onResolved: (score: number) => void }) {
  const options = complexityOptions([complexity.time, complexity.space])
  const [time, setTime] = useState('')
  const [space, setSpace] = useState('')
  const [done, setDone] = useState(false)
  const timeOk = sameComplexity(time, complexity.time)
  const spaceOk = sameComplexity(space, complexity.space)

  function check() {
    setDone(true)
    onResolved((timeOk ? 50 : 0) + (spaceOk ? 50 : 0))
  }

  const select = (id: string, label: string, v: string, set: (s: string) => void, ok: boolean) => (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-sm font-medium text-plum">
        {label}
      </label>
      <select id={id} value={v} onChange={(e) => set(e.target.value)} disabled={done} className={cn(fieldClass, done && (ok ? 'border-mint-deep' : 'border-destructive'))}>
        <option value="">Choose...</option>
        {options.map((o) => (
          <option key={o}>{o}</option>
        ))}
      </select>
    </div>
  )

  return (
    <Card className="space-y-5">
      <div>
        <p className="text-xs font-semibold tracking-wide text-coral-deep uppercase">Complexity check</p>
        <p className="mt-1 text-ink">What are the time and space complexity of the solution you just wrote?</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {select('time', 'Time complexity', time, setTime, timeOk)}
        {select('space', 'Space complexity', space, setSpace, spaceOk)}
      </div>
      {done ? (
        <p role="status" className="rounded-xl bg-ivory-deep px-4 py-3 text-sm text-ink">
          Expected time <strong>{complexity.time}</strong> and space <strong>{complexity.space}</strong>. {complexity.note}
        </p>
      ) : (
        <button type="button" onClick={check} disabled={!time || !space} className={primaryBtn}>
          Check complexity
        </button>
      )}
    </Card>
  )
}
