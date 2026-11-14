'use client'

import dynamic from 'next/dynamic'
import { CheckCircle2, Play, RotateCcw, Send, XCircle } from 'lucide-react'
import { Card, ghostBtn, primaryBtn } from '@/components/ui-kit'
import type { DemoResult } from '@/lib/arena'
import { LANGUAGES } from '@/lib/starters'
import type { Language } from '@/lib/types'
import { cn } from '@/lib/utils'

const Editor = dynamic(() => import('@monaco-editor/react'), {
  ssr: false,
  loading: () => <div className="grid h-full place-items-center bg-plum text-sm text-ivory/70">Loading editor...</div>,
})

interface Props {
  language: Language
  onLanguage: (l: Language) => void
  code: string
  onCode: (c: string) => void
  onReset: () => void
  onRun: () => void
  onSubmit: () => void
  result: DemoResult | null
  submitted: boolean
  disabled: boolean
}

export function CodePanel(p: Props) {
  const mono = LANGUAGES.find((l) => l.id === p.language)?.monaco ?? 'python'
  return (
    <div className="space-y-4">
      <Card className="overflow-hidden p-0">
        <div className="flex flex-wrap items-center gap-2 border-b border-border bg-ivory-deep/60 px-3 py-2">
          <label htmlFor="lang-select" className="sr-only">
            Language
          </label>
          <select id="lang-select" value={p.language} onChange={(e) => p.onLanguage(e.target.value as Language)} className="h-9 rounded-lg border border-input bg-card px-2.5 text-sm outline-none focus-visible:ring-3 focus-visible:ring-lavender/40">
            {LANGUAGES.map((l) => (
              <option key={l.id} value={l.id}>
                {l.label}
              </option>
            ))}
          </select>
          <button type="button" onClick={p.onReset} className="inline-flex h-9 items-center gap-1.5 rounded-lg px-2.5 text-sm text-muted-foreground hover:bg-card hover:text-plum">
            <RotateCcw className="size-3.5" /> Reset
          </button>
          <div className="ml-auto flex gap-2">
            <button type="button" onClick={p.onRun} disabled={p.disabled} className={cn(ghostBtn, 'h-9 px-3')}>
              <Play className="size-3.5" /> Run
            </button>
            <button type="button" onClick={p.onSubmit} disabled={p.disabled} className={cn(primaryBtn, 'h-9 px-3')}>
              <Send className="size-3.5" /> Submit
            </button>
          </div>
        </div>
        <div className="h-80 bg-plum" aria-label="Code editor">
          <Editor
            height="100%"
            language={mono}
            theme="vs-dark"
            value={p.code}
            onChange={(v) => p.onCode(v ?? '')}
            options={{ minimap: { enabled: false }, fontSize: 14, scrollBeyondLastLine: false, padding: { top: 12 }, tabSize: 4, automaticLayout: true, readOnly: p.disabled }}
          />
        </div>
      </Card>

      <Card className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="font-heading text-lg font-semibold text-plum">Results</h3>
          {p.result && (
            <span className={cn('rounded-full px-3 py-1 text-xs font-semibold', p.result.verdict === 'Accepted (demo)' ? 'bg-mint text-mint-deep' : 'bg-coral/20 text-coral-deep')}>
              {p.result.verdict} &middot; {p.result.passed}/{p.result.total}
            </span>
          )}
        </div>
        {p.result ? (
          <ul className="space-y-2" aria-live="polite">
            {p.result.rows.map((r, i) => (
              <li key={i} className="flex items-center gap-2.5 rounded-lg bg-ivory-deep/60 px-3 py-2 font-mono text-xs">
                {r.ok ? <CheckCircle2 className="size-4 shrink-0 text-mint-deep" /> : <XCircle className="size-4 shrink-0 text-destructive" />}
                <span className="truncate">{r.label}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">Run your code to see how it does against the example tests.</p>
        )}
        <p className="text-xs text-muted-foreground">Demo judge: this checks the structure of your solution against what a correct one needs. Real code execution arrives with the backend.</p>
      </Card>
    </div>
  )
}
