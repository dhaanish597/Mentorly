import type { PersistedState } from '@/lib/types'
import { LEVELS, PATHS, isLevelUnlocked } from '@/lib/data'

const LEVEL_TITLES = ['Curious Learner', 'Pattern Seeker', 'Sharp Thinker', 'Clear Communicator', 'Problem Solver', 'Interview Ready', 'Mentor Material']

export function levelForXp(xp: number) {
  const level = Math.floor(Math.sqrt(Math.max(0, xp) / 60)) + 1
  const floor = 60 * (level - 1) ** 2
  const ceiling = 60 * level ** 2
  return {
    level,
    title: LEVEL_TITLES[Math.min(level - 1, LEVEL_TITLES.length - 1)],
    floor,
    ceiling,
    progress: Math.round(((xp - floor) / (ceiling - floor)) * 100),
    toNext: ceiling - xp,
  }
}

export interface BadgeDef {
  id: string
  name: string
  description: string
  tone: 'coral' | 'mint' | 'lavender' | 'plum'
  icon: 'sparkles' | 'brain' | 'target' | 'flame' | 'lock-open' | 'compass' | 'trophy' | 'feather'
  earned: (s: PersistedState) => boolean
}

const scores = (s: PersistedState) => Object.values(s.completions)

export const BADGES: BadgeDef[] = [
  { id: 'first-step', name: 'First Step', description: 'Complete your first challenge.', tone: 'coral', icon: 'sparkles', earned: (s) => scores(s).length >= 1 },
  { id: 'clear-thinker', name: 'Clear Thinker', description: 'Score 80+ for reasoning on a challenge.', tone: 'lavender', icon: 'brain', earned: (s) => scores(s).some((c) => c.scores.reasoning >= 80) },
  { id: 'sharp-predictor', name: 'Sharp Predictor', description: 'Predict an output perfectly.', tone: 'mint', icon: 'target', earned: (s) => scores(s).some((c) => c.scores.prediction === 100) },
  { id: 'no-hints', name: 'Unassisted', description: 'Finish a challenge without any hints.', tone: 'plum', icon: 'feather', earned: (s) => scores(s).some((c) => c.hintsUsed === 0) },
  { id: 'streak-3', name: 'Three-Day Streak', description: 'Practise three days in a row.', tone: 'coral', icon: 'flame', earned: (s) => s.streak >= 3 },
  { id: 'level-key', name: 'Level Key', description: 'Unlock a new level in any path.', tone: 'mint', icon: 'lock-open', earned: (s) => PATHS.some((p) => LEVELS.slice(1).some((l) => isLevelUnlocked(p.id, l.id, s.completions))) },
  { id: 'explorer', name: 'Path Explorer', description: 'Complete a challenge in all three paths.', tone: 'lavender', icon: 'compass', earned: (s) => PATHS.every((p) => scores(s).some((c) => c.challengeId.startsWith(p.id === 'dsa' ? 'dsa-' : p.id === 'aptitude' ? 'apt-' : 'ver-'))) },
  { id: 'xp-500', name: 'Five Hundred', description: 'Reach 500 XP.', tone: 'plum', icon: 'trophy', earned: (s) => s.xp >= 500 },
]

export function today() {
  return new Date().toISOString().slice(0, 10)
}

export function daysBetween(a: string, b: string) {
  return Math.round((new Date(b).getTime() - new Date(a).getTime()) / 86_400_000)
}
