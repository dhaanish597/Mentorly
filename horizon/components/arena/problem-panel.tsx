import { Card, Pill } from '@/components/ui-kit'
import type { Challenge } from '@/lib/types'

export function ProblemPanel({ challenge: c }: { challenge: Challenge }) {
  return (
    <Card className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <Pill tone={c.difficulty === 'Easy' ? 'mint' : c.difficulty === 'Medium' ? 'lavender' : 'coral'}>{c.difficulty}</Pill>
        <Pill>{c.topic}</Pill>
        <Pill tone="plum">{c.xp} XP</Pill>
      </div>
      <p className="leading-relaxed text-pretty text-ink">{c.statement}</p>
      {(c.inputFormat || c.outputFormat) && (
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          {c.inputFormat && (
            <div>
              <dt className="font-semibold text-plum">Input</dt>
              <dd className="text-muted-foreground">{c.inputFormat}</dd>
            </div>
          )}
          {c.outputFormat && (
            <div>
              <dt className="font-semibold text-plum">Output</dt>
              <dd className="text-muted-foreground">{c.outputFormat}</dd>
            </div>
          )}
        </dl>
      )}
      {c.examples.length > 0 && (
        <div className="space-y-3">
          <h3 className="font-heading text-lg font-semibold text-plum">Examples</h3>
          {c.examples.map((e, i) => (
            <div key={i} className="rounded-xl bg-ivory-deep/70 p-4 text-sm">
              <p className="font-mono text-xs text-muted-foreground">Input</p>
              <p className="font-mono whitespace-pre-wrap text-ink">{e.input}</p>
              <p className="mt-2 font-mono text-xs text-muted-foreground">Output</p>
              <p className="font-mono whitespace-pre-wrap text-ink">{e.output}</p>
              {e.explanation && <p className="mt-2 text-muted-foreground">{e.explanation}</p>}
            </div>
          ))}
        </div>
      )}
      {c.constraints.length > 0 && (
        <div>
          <h3 className="font-heading text-lg font-semibold text-plum">Constraints</h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {c.constraints.map((k) => (
              <li key={k} className="font-mono text-xs">
                {k}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  )
}
