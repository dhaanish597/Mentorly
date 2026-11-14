'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { LogOut } from 'lucide-react'
import { Page } from '@/components/app-shell'
import { PasswordInput } from '@/components/auth/auth-shell'
import { Card, PageHeader, fieldClass, ghostBtn, primaryBtn } from '@/components/ui-kit'
import { LANGUAGES } from '@/lib/starters'
import { levelForXp } from '@/lib/gamification'
import { useStore } from '@/lib/store'
import type { Language } from '@/lib/types'
import { cn } from '@/lib/utils'

function Toggle({ checked, onChange, label, description }: { checked: boolean; onChange: (v: boolean) => void; label: string; description?: string }) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-4 py-2">
      <span>
        <span className="block text-sm font-medium text-plum">{label}</span>
        {description && <span className="block text-xs text-muted-foreground">{description}</span>}
      </span>
      <button type="button" role="switch" aria-checked={checked} aria-label={label} onClick={() => onChange(!checked)} className={cn('relative h-6 w-11 shrink-0 rounded-full transition focus-visible:ring-3 focus-visible:ring-lavender/50 focus-visible:outline-none', checked ? 'bg-coral' : 'bg-input')}>
        <span className={cn('absolute top-0.5 left-0.5 size-5 rounded-full bg-white shadow transition-transform', checked && 'translate-x-5')} />
      </button>
    </label>
  )
}

export default function ProfilePage() {
  const { user, state, updateProfile, updateSettings, changePassword, signOut, pushToast } = useStore()
  const router = useRouter()
  const [name, setName] = useState(user?.name ?? '')
  const [email, setEmail] = useState(user?.email ?? '')
  const [profileError, setProfileError] = useState('')
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [pwError, setPwError] = useState('')
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([])
  const [mics, setMics] = useState<MediaDeviceInfo[]>([])
  const lvl = levelForXp(state.xp)

  useEffect(() => {
    if (typeof speechSynthesis === 'undefined') return
    const load = () => setVoices(speechSynthesis.getVoices())
    load()
    speechSynthesis.addEventListener('voiceschanged', load)
    return () => speechSynthesis.removeEventListener('voiceschanged', load)
  }, [])

  useEffect(() => {
    navigator.mediaDevices?.enumerateDevices?.().then((d) => setMics(d.filter((x) => x.kind === 'audioinput'))).catch(() => setMics([]))
  }, [])

  function saveProfile(e: React.FormEvent) {
    e.preventDefault()
    if (name.trim().length < 2) return setProfileError('Name must be at least 2 characters.')
    if (!/^\S+@\S+\.\S+$/.test(email)) return setProfileError('Enter a valid email address.')
    const res = updateProfile({ name: name.trim(), email: email.trim() })
    if (res.error) return setProfileError(res.error)
    setProfileError('')
    pushToast('Profile updated.', 'success')
  }

  async function savePassword(e: React.FormEvent) {
    e.preventDefault()
    if (next.length < 8) return setPwError('New password must be at least 8 characters.')
    const res = await changePassword(current, next)
    if (res.error) return setPwError(res.error)
    setPwError('')
    setCurrent('')
    setNext('')
    pushToast('Password changed.', 'success')
  }

  const { settings } = state

  return (
    <Page className="max-w-4xl">
      <PageHeader eyebrow="Profile" title="Your account and preferences" />

      <Card className="flex flex-wrap items-center gap-5">
        <div className="grid size-16 place-items-center rounded-full bg-coral font-heading text-2xl font-semibold text-plum">{user?.name.charAt(0).toUpperCase()}</div>
        <div className="flex-1">
          <p className="font-heading text-xl font-semibold text-plum">{user?.name}</p>
          <p className="text-sm text-muted-foreground">
            Level {lvl.level} &middot; {lvl.title} &middot; {state.xp} XP
          </p>
          <p className="text-xs text-muted-foreground">Joined {user && new Date(user.createdAt).toLocaleDateString(undefined, { dateStyle: 'medium' })}</p>
        </div>
        <button
          type="button"
          className={ghostBtn}
          onClick={() => {
            signOut()
            router.replace('/')
          }}
        >
          <LogOut className="size-4" /> Sign out
        </button>
      </Card>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <h2 className="font-heading text-xl font-semibold text-plum">Account</h2>
          <form onSubmit={saveProfile} className="mt-4 space-y-4" noValidate>
            <div className="space-y-1.5">
              <label htmlFor="p-name" className="text-sm font-medium text-plum">
                Name
              </label>
              <input id="p-name" value={name} onChange={(e) => setName(e.target.value)} className={fieldClass} />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="p-email" className="text-sm font-medium text-plum">
                Email
              </label>
              <input id="p-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} className={fieldClass} />
            </div>
            {profileError && (
              <p role="alert" className="text-sm text-destructive">
                {profileError}
              </p>
            )}
            <button type="submit" className={primaryBtn}>
              Save changes
            </button>
          </form>
        </Card>

        <Card>
          <h2 className="font-heading text-xl font-semibold text-plum">Change password</h2>
          <form onSubmit={savePassword} className="mt-4 space-y-4" noValidate>
            <div className="space-y-1.5">
              <label htmlFor="cur" className="text-sm font-medium text-plum">
                Current password
              </label>
              <PasswordInput id="cur" value={current} onChange={setCurrent} autoComplete="current-password" />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="new" className="text-sm font-medium text-plum">
                New password
              </label>
              <PasswordInput id="new" value={next} onChange={setNext} autoComplete="new-password" />
            </div>
            {pwError && (
              <p role="alert" className="text-sm text-destructive">
                {pwError}
              </p>
            )}
            <button type="submit" className={primaryBtn} disabled={!current || !next}>
              Update password
            </button>
          </form>
        </Card>
      </div>

      <Card>
        <h2 className="font-heading text-xl font-semibold text-plum">Mentor and practice</h2>
        <div className="mt-4 grid gap-5 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label htmlFor="lang" className="text-sm font-medium text-plum">
              Preferred language
            </label>
            <select id="lang" value={settings.language} onChange={(e) => updateSettings({ language: e.target.value as Language })} className={fieldClass}>
              {LANGUAGES.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.label}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="voice" className="text-sm font-medium text-plum">
              Mentor voice
            </label>
            <select id="voice" value={settings.voiceName} onChange={(e) => updateSettings({ voiceName: e.target.value })} className={fieldClass}>
              <option value="">Browser default</option>
              {voices.map((v) => (
                <option key={v.name} value={v.name}>
                  {v.name} ({v.lang})
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="rate" className="text-sm font-medium text-plum">
              Speech speed: {settings.speechRate.toFixed(1)}x
            </label>
            <input id="rate" type="range" min={0.7} max={1.4} step={0.1} value={settings.speechRate} onChange={(e) => updateSettings({ speechRate: Number(e.target.value) })} className="h-11 w-full accent-coral" />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="mic" className="text-sm font-medium text-plum">
              Microphone
            </label>
            <select id="mic" value={settings.micDeviceId} onChange={(e) => updateSettings({ micDeviceId: e.target.value })} className={fieldClass}>
              <option value="">System default</option>
              {mics.map((m, i) => (
                <option key={m.deviceId || i} value={m.deviceId}>
                  {m.label || `Microphone ${i + 1}`}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="mt-4 divide-y divide-border">
          <Toggle checked={settings.autoSpeak} onChange={(v) => updateSettings({ autoSpeak: v })} label="Mentor speaks automatically" description="Reads each mentor message aloud. Always off if your browser has no speech support." />
          <Toggle checked={settings.notifications.daily} onChange={(v) => updateSettings({ notifications: { ...settings.notifications, daily: v } })} label="Daily practice reminder" />
          <Toggle checked={settings.notifications.streak} onChange={(v) => updateSettings({ notifications: { ...settings.notifications, streak: v } })} label="Streak at risk alerts" />
          <Toggle checked={settings.notifications.weekly} onChange={(v) => updateSettings({ notifications: { ...settings.notifications, weekly: v } })} label="Weekly progress summary" />
        </div>
        <p className="mt-3 text-xs text-muted-foreground">Notification preferences are saved now and will take effect once email delivery is connected.</p>
      </Card>
    </Page>
  )
}
