import type { Challenge, Language, SubmissionRecord } from '@/lib/types'

export type Stage = 'explain' | 'code' | 'concept' | 'predict' | 'complexity' | 'reflect' | 'done'

export const STAGE_LABEL: Record<Stage, string> = {
  explain: 'Explain',
  code: 'Code',
  concept: 'Answer',
  predict: 'Predict',
  complexity: 'Complexity',
  reflect: 'Reflect',
  done: 'Done',
}

export function stagesFor(c: Challenge): Stage[] {
  if (c.kind === 'mcq') return ['explain', 'concept', ...(c.fresh.mcq ? (['predict'] as Stage[]) : []), 'reflect']
  return ['explain', 'code', ...(c.fresh.code ? (['predict'] as Stage[]) : []), ...(c.complexity ? (['complexity'] as Stage[]) : []), 'reflect']
}

export const normalize = (s: string) => s.toLowerCase().replace(/[^a-z0-9\s]/g, ' ').replace(/\s+/g, ' ').trim()
export const wordCount = (s: string) => normalize(s).split(' ').filter(Boolean).length

export function keywordHits(text: string, keywords: string[]) {
  const n = normalize(text)
  return keywords.filter((k) => n.includes(k.toLowerCase())).length
}

export type Quality = 'thin' | 'ok' | 'strong'

export function judgeAnswer(text: string, c: Challenge): { quality: Quality; hits: number; score: number } {
  const words = wordCount(text)
  const hits = keywordHits(text, c.reasoningKeywords)
  const score = Math.max(0, Math.min(100, Math.round(Math.min(words, 30) * 1.2 + Math.min(hits, 5) * 12)))
  const quality: Quality = words < 8 || (hits === 0 && words < 20) ? 'thin' : hits >= 3 ? 'strong' : 'ok'
  return { quality, hits, score }
}

export const normalizeAnswer = (s: string) => s.toLowerCase().replace(/["'`\s]/g, '').replace(/^\[|\]$/g, '').replace(/,$/, '')

export const COMPLEXITY_OPTIONS = ['O(1)', 'O(log n)', 'O(n)', 'O(n log n)', 'O(n^2)', 'O(n^3)', 'O(2^n)']

export function complexityOptions(expected: string[]) {
  const norm = (s: string) => s.replace(/\s/g, '').toLowerCase()
  const extra = expected.filter((e) => !COMPLEXITY_OPTIONS.some((o) => norm(o) === norm(e)))
  return [...COMPLEXITY_OPTIONS, ...extra]
}

export const sameComplexity = (a: string, b: string) => a.replace(/\s/g, '').toLowerCase() === b.replace(/\s/g, '').toLowerCase()

export interface DemoResult {
  passed: number
  total: number
  verdict: SubmissionRecord['verdict']
  rows: { label: string; hidden: boolean; ok: boolean }[]
}

/** Heuristic stand-in for a real judge: checks that the code is non-trivial and contains the structures the solution needs. */
export function demoJudge(c: Challenge, code: string, starter: string, lang: Language): DemoResult {
  const tests = c.tests ?? []
  const stripped = code.replace(/\s+/g, '')
  const untouched = stripped === starter.replace(/\s+/g, '') || stripped.length < starter.replace(/\s+/g, '').length + 8
  const groups = c.demoChecks ?? []
  const matched = groups.filter((g) => g.some((src) => new RegExp(src, 'i').test(code))).length
  const ratio = untouched ? 0 : groups.length ? matched / groups.length : 1
  const passed = Math.floor(tests.length * ratio)
  void lang
  return {
    passed,
    total: tests.length,
    verdict: untouched ? 'Not implemented' : passed === tests.length ? 'Accepted (demo)' : 'Wrong answer (demo)',
    rows: tests.map((t, i) => ({ label: t.hidden ? `Hidden test ${i + 1}` : t.input, hidden: !!t.hidden, ok: i < passed })),
  }
}

const pick = <T,>(xs: T[], seed: number) => xs[Math.abs(seed) % xs.length]

export const mentorLines = {
  intro: (name: string, c: Challenge) =>
    `Hi ${name}. Today's challenge is "${c.title}". Before any code, tell me in your own words what this is asking and how you would start. Speak or type, whichever feels natural.`,
  thin: (c: Challenge) => `I would like a little more to work with. ${c.hints[0] ?? 'Walk me through your first step.'}`,
  affirmCode: (n: number) =>
    pick(
      [
        'That is a clear way to begin. Now turn it into code. I will be here with questions when you need them.',
        'Good, you have a plan. Write it down in code and run it when you are ready.',
        'Nice reasoning. Let us see it become a solution.',
      ],
      n,
    ),
  affirmMcq: 'Good thinking. Now choose the answer that matches your reasoning.',
  codeFail: (c: Challenge, ratioText: string) => `${ratioText} Pick the first example and trace it by hand, line by line. Where does your code first disagree with the expected output? ${c.hints[1] ? 'Think about this: ' + c.hints[1] : ''}`,
  codePass: 'All checks pass. Now I want to see whether you can predict, not just write.',
  predictIntro: (prompt: string) => prompt,
  predictWrong: 'Not quite. Trace the input through your logic one step at a time, then try again.',
  predictRight: 'Exactly. You can see how the code behaves without running it.',
  complexityRight: 'Spot on. You know what your solution costs.',
  complexityWrong: (note: string) => `Close, but not quite. ${note}`,
  reflectAck: (n: number) => pick(['Thank you. That helps me see how you think.', 'Interesting. Hold that thought.', 'Understood, and well explained.'], n),
  thinReflect: 'Try giving one concrete reason or example, then we will move on.',
  finish: 'That is the whole conversation. Let us see how you did.',
  hintIntro: (n: number) => `Here is a question to think about (hint ${n}):`,
  noMoreHints: 'You have used every hint for this challenge. Trust your reasoning and try the next step.',
}
