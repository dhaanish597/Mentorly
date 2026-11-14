export type PathId = 'dsa' | 'aptitude' | 'verbal'
export type LevelId = 'beginner' | 'intermediate' | 'advanced'
export type Language = 'python' | 'cpp' | 'java' | 'c'
export type Difficulty = 'Easy' | 'Medium' | 'Hard'
export type ParamType = 'int[]' | 'int' | 'string' | 'bool'

export interface TestCase {
  input: string
  expected: string
  hidden?: boolean
}

export interface Example {
  input: string
  output: string
  explanation?: string
}

export interface FnSpec {
  name: string
  params: { name: string; type: ParamType }[]
  returns: ParamType
}

export interface McqQuestion {
  question: string
  options: string[]
  answerIndex: number
  explanation: string
}

export interface FreshCode {
  prompt: string
  input: string
  expected: string
}

export interface Complexity {
  time: string
  space: string
  note: string
}

export interface Challenge {
  id: string
  pathId: PathId
  level: LevelId
  topic: string
  title: string
  difficulty: Difficulty
  xp: number
  objective: string
  kind: 'code' | 'mcq'
  statement: string
  inputFormat?: string
  outputFormat?: string
  constraints: string[]
  examples: Example[]
  fn?: FnSpec
  tests?: TestCase[]
  /** Groups of alternative regex sources; every group must match for the demo verdict to pass. */
  demoChecks?: string[][]
  complexity?: Complexity
  mcq?: McqQuestion
  fresh: { code?: FreshCode; mcq?: McqQuestion }
  hints: string[]
  concept: string
  reasoningKeywords: string[]
  whyPrompt: string
  alternativePrompt?: string
  edgePrompt?: string
}

export interface LevelDef {
  id: LevelId
  name: string
  tagline: string
  requiredToUnlockNext: number
}

export interface TopicDef {
  name: string
}

export interface PathDef {
  id: PathId
  name: string
  fullName: string
  description: string
  accent: 'coral' | 'mint' | 'lavender'
  topics: string[]
}

export interface ScoreSet {
  code: number | null
  reasoning: number
  prediction: number | null
  concept: number
  complexity: number | null
}

export interface CompletionRecord {
  challengeId: string
  completedAt: string
  scores: ScoreSet
  hintsUsed: number
  xpEarned: number
}

export interface SubmissionRecord {
  id: string
  challengeId: string
  language: Language
  at: string
  passed: number
  total: number
  verdict: 'Accepted (demo)' | 'Wrong answer (demo)' | 'Not implemented'
  code: string
}

export interface XpTransaction {
  id: string
  at: string
  amount: number
  reason: string
  challengeId?: string
}

export interface ActivityItem {
  id: string
  at: string
  text: string
  kind: 'xp' | 'complete' | 'badge' | 'level' | 'streak'
}

export interface UserSettings {
  language: Language
  voiceName: string
  speechRate: number
  autoSpeak: boolean
  micDeviceId: string
  notifications: { daily: boolean; streak: boolean; weekly: boolean }
}

export interface UserProfile {
  id: string
  name: string
  email: string
  createdAt: string
}

export interface SavedDraft {
  [key: string]: string
}

export interface PersistedState {
  user: UserProfile | null
  xp: number
  streak: number
  lastActiveDate: string | null
  activeDays: string[]
  completions: Record<string, CompletionRecord>
  submissions: SubmissionRecord[]
  transactions: XpTransaction[]
  activity: ActivityItem[]
  badges: string[]
  drafts: SavedDraft
  settings: UserSettings
}
