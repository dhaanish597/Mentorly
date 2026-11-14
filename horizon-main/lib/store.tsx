'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { BADGES, daysBetween, levelForXp, today, type BadgeDef } from '@/lib/gamification'
import { CHALLENGES, LEVELS, PATHS, isLevelUnlocked } from '@/lib/data'
import type {
  ActivityItem,
  CompletionRecord,
  PersistedState,
  ScoreSet,
  SubmissionRecord,
  UserProfile,
  UserSettings,
} from '@/lib/types'

/*
 * DEMO MODE
 * Accounts and progress live in this browser's localStorage so the full student journey can be explored
 * without a backend. Every function below is the seam where Supabase Auth + PostgreSQL will plug in.
 */

const SESSION_KEY = 'mentorly.demo.session'
const USERS_KEY = 'mentorly.demo.users'
const dataKey = (id: string) => `mentorly.demo.data.${id}`

interface DemoUser extends UserProfile {
  hash: string
  resetToken?: string
}

export const DEFAULT_SETTINGS: UserSettings = {
  language: 'python',
  voiceName: '',
  speechRate: 1,
  autoSpeak: true,
  micDeviceId: '',
  notifications: { daily: true, streak: true, weekly: false },
}

const emptyState = (user: UserProfile | null): PersistedState => ({
  user,
  xp: 0,
  streak: 0,
  lastActiveDate: null,
  activeDays: [],
  completions: {},
  submissions: [],
  transactions: [],
  activity: [],
  badges: [],
  drafts: {},
  settings: DEFAULT_SETTINGS,
})

async function hash(value: string) {
  const bytes = new TextEncoder().encode(`mentorly::${value}`)
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, '0')).join('')
}

const readUsers = (): DemoUser[] => {
  try {
    return JSON.parse(localStorage.getItem(USERS_KEY) ?? '[]')
  } catch {
    return []
  }
}
const writeUsers = (users: DemoUser[]) => localStorage.setItem(USERS_KEY, JSON.stringify(users))

export interface XpAward {
  amount: number
  reason: string
}

export interface CompletionInput {
  challengeId: string
  scores: ScoreSet
  hintsUsed: number
  awards: XpAward[]
}

export interface CompletionResult {
  total: number
  awards: XpAward[]
  newBadges: BadgeDef[]
  levelUp: { from: number; to: number; title: string } | null
  unlocked: { pathName: string; levelName: string }[]
  alreadyCompleted: boolean
}

export interface Toast {
  id: string
  text: string
  tone: 'xp' | 'info' | 'success' | 'error'
}

const uid = () => Math.random().toString(36).slice(2, 10)

function touchStreak(s: PersistedState): PersistedState {
  const t = today()
  if (s.lastActiveDate === t) return s
  const streak = s.lastActiveDate && daysBetween(s.lastActiveDate, t) === 1 ? s.streak + 1 : 1
  return { ...s, streak, lastActiveDate: t, activeDays: Array.from(new Set([...s.activeDays, t])) }
}

function unlockedSet(completions: PersistedState['completions']) {
  const out = new Set<string>()
  for (const p of PATHS) for (const l of LEVELS) if (isLevelUnlocked(p.id, l.id, completions)) out.add(`${p.id}:${l.id}`)
  return out
}

interface Store {
  ready: boolean
  state: PersistedState
  user: UserProfile | null
  toasts: Toast[]
  dismissToast: (id: string) => void
  pushToast: (text: string, tone?: Toast['tone']) => void
  signUp: (name: string, email: string, password: string) => Promise<{ error?: string }>
  signIn: (email: string, password: string) => Promise<{ error?: string }>
  signOut: () => void
  requestPasswordReset: (email: string) => Promise<{ token?: string }>
  resetPassword: (email: string, token: string, password: string) => Promise<{ error?: string }>
  changePassword: (current: string, next: string) => Promise<{ error?: string }>
  updateProfile: (patch: { name?: string; email?: string }) => { error?: string }
  updateSettings: (patch: Partial<UserSettings>) => void
  saveDraft: (key: string, code: string) => void
  recordSubmission: (s: Omit<SubmissionRecord, 'id' | 'at'>) => void
  completeChallenge: (input: CompletionInput) => CompletionResult
  awardXp: (amount: number, reason: string, challengeId?: string) => void
  seedSampleProgress: () => void
  resetProgress: () => void
}

const Ctx = createContext<Store | null>(null)

export function StoreProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false)
  const [state, setState] = useState<PersistedState>(emptyState(null))
  const [toasts, setToasts] = useState<Toast[]>([])
  const ref = useRef(state)
  ref.current = state

  useEffect(() => {
    try {
      const id = localStorage.getItem(SESSION_KEY)
      if (id) {
        const user = readUsers().find((u) => u.id === id)
        const saved = localStorage.getItem(dataKey(id))
        if (user && saved) {
          const parsed = JSON.parse(saved) as PersistedState
          setState({ ...emptyState(null), ...parsed, settings: { ...DEFAULT_SETTINGS, ...parsed.settings } })
        } else if (user) {
          setState(emptyState({ id: user.id, name: user.name, email: user.email, createdAt: user.createdAt }))
        }
      }
    } catch {
      /* corrupt demo data is ignored */
    }
    setReady(true)
  }, [])

  useEffect(() => {
    if (!ready || !state.user) return
    localStorage.setItem(dataKey(state.user.id), JSON.stringify(state))
  }, [state, ready])

  const commit = useCallback((next: PersistedState) => {
    ref.current = next
    setState(next)
  }, [])

  const pushToast = useCallback((text: string, tone: Toast['tone'] = 'info') => {
    const id = uid()
    setToasts((t) => [...t.slice(-3), { id, text, tone }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200)
  }, [])
  const dismissToast = useCallback((id: string) => setToasts((t) => t.filter((x) => x.id !== id)), [])

  const startSession = useCallback(
    (u: DemoUser) => {
      localStorage.setItem(SESSION_KEY, u.id)
      const saved = localStorage.getItem(dataKey(u.id))
      const profile: UserProfile = { id: u.id, name: u.name, email: u.email, createdAt: u.createdAt }
      if (saved) {
        const parsed = JSON.parse(saved) as PersistedState
        commit({ ...parsed, user: profile, settings: { ...DEFAULT_SETTINGS, ...parsed.settings } })
      } else commit(emptyState(profile))
    },
    [commit],
  )

  const signUp: Store['signUp'] = useCallback(
    async (name, email, password) => {
      const users = readUsers()
      if (users.some((u) => u.email.toLowerCase() === email.toLowerCase()))
        return { error: 'An account with this email already exists. Try signing in instead.' }
      const user: DemoUser = { id: uid() + uid(), name: name.trim(), email: email.trim(), createdAt: new Date().toISOString(), hash: await hash(password) }
      writeUsers([...users, user])
      startSession(user)
      return {}
    },
    [startSession],
  )

  const signIn: Store['signIn'] = useCallback(
    async (email, password) => {
      const user = readUsers().find((u) => u.email.toLowerCase() === email.trim().toLowerCase())
      if (!user || user.hash !== (await hash(password))) return { error: 'Invalid email or password.' }
      startSession(user)
      return {}
    },
    [startSession],
  )

  const signOut = useCallback(() => {
    localStorage.removeItem(SESSION_KEY)
    commit(emptyState(null))
  }, [commit])

  const requestPasswordReset: Store['requestPasswordReset'] = useCallback(async (email) => {
    const users = readUsers()
    const user = users.find((u) => u.email.toLowerCase() === email.trim().toLowerCase())
    if (!user) return {}
    const token = uid() + uid()
    user.resetToken = token
    writeUsers(users)
    return { token }
  }, [])

  const resetPassword: Store['resetPassword'] = useCallback(async (email, token, password) => {
    const users = readUsers()
    const user = users.find((u) => u.email.toLowerCase() === email.trim().toLowerCase())
    if (!user || !user.resetToken || user.resetToken !== token) return { error: 'This reset link is invalid or has expired.' }
    user.hash = await hash(password)
    delete user.resetToken
    writeUsers(users)
    return {}
  }, [])

  const changePassword: Store['changePassword'] = useCallback(async (current, next) => {
    const id = ref.current.user?.id
    const users = readUsers()
    const user = users.find((u) => u.id === id)
    if (!user || user.hash !== (await hash(current))) return { error: 'Your current password is incorrect.' }
    user.hash = await hash(next)
    writeUsers(users)
    return {}
  }, [])

  const updateProfile: Store['updateProfile'] = useCallback(
    (patch) => {
      const cur = ref.current
      if (!cur.user) return { error: 'Not signed in.' }
      const users = readUsers()
      if (patch.email && users.some((u) => u.id !== cur.user!.id && u.email.toLowerCase() === patch.email!.toLowerCase()))
        return { error: 'That email is already used by another account.' }
      const me = users.find((u) => u.id === cur.user!.id)
      if (me) {
        if (patch.name) me.name = patch.name
        if (patch.email) me.email = patch.email
        writeUsers(users)
      }
      commit({ ...cur, user: { ...cur.user, ...patch } })
      return {}
    },
    [commit],
  )

  const updateSettings = useCallback((patch: Partial<UserSettings>) => commit({ ...ref.current, settings: { ...ref.current.settings, ...patch } }), [commit])
  const saveDraft = useCallback((key: string, code: string) => commit({ ...ref.current, drafts: { ...ref.current.drafts, [key]: code } }), [commit])
  const recordSubmission = useCallback(
    (s: Omit<SubmissionRecord, 'id' | 'at'>) =>
      commit({ ...ref.current, submissions: [{ ...s, id: uid(), at: new Date().toISOString() }, ...ref.current.submissions].slice(0, 200) }),
    [commit],
  )

  const awardXp = useCallback(
    (amount: number, reason: string, challengeId?: string) => {
      const cur = touchStreak(ref.current)
      const at = new Date().toISOString()
      const activity: ActivityItem = { id: uid(), at, text: `+${amount} XP: ${reason}`, kind: 'xp' }
      commit({
        ...cur,
        xp: cur.xp + amount,
        transactions: [{ id: uid(), at, amount, reason, challengeId }, ...cur.transactions].slice(0, 300),
        activity: [activity, ...cur.activity].slice(0, 60),
      })
      pushToast(`+${amount} XP  ${reason}`, 'xp')
    },
    [commit, pushToast],
  )

  const completeChallenge: Store['completeChallenge'] = useCallback(
    ({ challengeId, scores, hintsUsed, awards }) => {
      const prev = ref.current
      if (prev.completions[challengeId])
        return { total: 0, awards: [], newBadges: [], levelUp: null, unlocked: [], alreadyCompleted: true }
      const challenge = CHALLENGES.find((c) => c.id === challengeId)!
      const total = awards.reduce((n, a) => n + a.amount, 0)
      const at = new Date().toISOString()
      let next = touchStreak(prev)
      const record: CompletionRecord = { challengeId, completedAt: at, scores, hintsUsed, xpEarned: total }
      next = {
        ...next,
        xp: next.xp + total,
        completions: { ...next.completions, [challengeId]: record },
        transactions: [...awards.map((a) => ({ id: uid(), at, amount: a.amount, reason: a.reason, challengeId })), ...next.transactions].slice(0, 300),
        activity: [{ id: uid(), at, text: `Completed "${challenge.title}" and earned ${total} XP`, kind: 'complete' as const }, ...next.activity].slice(0, 60),
      }
      const before = unlockedSet(prev.completions)
      const after = unlockedSet(next.completions)
      const unlocked = [...after]
        .filter((k) => !before.has(k))
        .map((k) => {
          const [pid, lid] = k.split(':')
          return { pathName: PATHS.find((p) => p.id === pid)!.name, levelName: LEVELS.find((l) => l.id === lid)!.name }
        })
      const newBadges = BADGES.filter((b) => !next.badges.includes(b.id) && b.earned(next))
      if (newBadges.length) {
        next = {
          ...next,
          badges: [...next.badges, ...newBadges.map((b) => b.id)],
          activity: [...newBadges.map((b) => ({ id: uid(), at, text: `Badge earned: ${b.name}`, kind: 'badge' as const })), ...next.activity].slice(0, 60),
        }
      }
      const from = levelForXp(prev.xp).level
      const to = levelForXp(next.xp)
      commit(next)
      return { total, awards, newBadges, unlocked, levelUp: to.level > from ? { from, to: to.level, title: to.title } : null, alreadyCompleted: false }
    },
    [commit],
  )

  const seedSampleProgress = useCallback(() => {
    const cur = ref.current
    const sample = ['dsa-second-largest', 'dsa-valid-palindrome', 'dsa-binary-search', 'dsa-sort-colors', 'apt-percent-swing', 'apt-ratio-share', 'apt-profit-loss', 'ver-grammar-agreement', 'ver-vocab-ephemeral']
    const completions = { ...cur.completions }
    const transactions = [...cur.transactions]
    const activity = [...cur.activity]
    const activeDays = new Set(cur.activeDays)
    let xp = cur.xp
    sample.forEach((id, i) => {
      if (completions[id]) return
      const ch = CHALLENGES.find((c) => c.id === id)!
      const d = new Date(Date.now() - (sample.length - i) * 0.8 * 86_400_000)
      const at = d.toISOString()
      activeDays.add(at.slice(0, 10))
      const wobble = (i * 7) % 15
      const scores: ScoreSet = {
        code: ch.kind === 'code' ? 70 + wobble + 10 : null,
        reasoning: 58 + wobble + i * 2,
        prediction: ch.kind === 'code' ? 50 + wobble * 2 : null,
        concept: 62 + wobble,
        complexity: ch.kind === 'code' ? 55 + wobble : null,
      }
      const earned = ch.xp + 12
      xp += earned
      completions[id] = { challengeId: id, completedAt: at, scores, hintsUsed: i % 3, xpEarned: earned }
      transactions.unshift({ id: uid(), at, amount: earned, reason: `Completed ${ch.title}`, challengeId: id })
      activity.unshift({ id: uid(), at, text: `Completed "${ch.title}" and earned ${earned} XP`, kind: 'complete' })
    })
    let next: PersistedState = { ...cur, completions, transactions, activity: activity.slice(0, 60), activeDays: [...activeDays], xp, streak: Math.max(cur.streak, 4), lastActiveDate: today() }
    next = { ...next, badges: BADGES.filter((b) => b.earned(next)).map((b) => b.id) }
    commit(next)
    pushToast('Sample progress loaded (demo data).', 'info')
  }, [commit, pushToast])

  const resetProgress = useCallback(() => {
    const cur = ref.current
    commit({ ...emptyState(cur.user), settings: cur.settings })
    pushToast('Progress reset.', 'info')
  }, [commit, pushToast])

  const value = useMemo<Store>(
    () => ({
      ready, state, user: state.user, toasts, dismissToast, pushToast, signUp, signIn, signOut, requestPasswordReset, resetPassword, changePassword,
      updateProfile, updateSettings, saveDraft, recordSubmission, completeChallenge, awardXp, seedSampleProgress, resetProgress,
    }),
    [ready, state, toasts, dismissToast, pushToast, signUp, signIn, signOut, requestPasswordReset, resetPassword, changePassword, updateProfile, updateSettings, saveDraft, recordSubmission, completeChallenge, awardXp, seedSampleProgress, resetProgress],
  )

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useStore() {
  const v = useContext(Ctx)
  if (!v) throw new Error('useStore must be used inside StoreProvider')
  return v
}
