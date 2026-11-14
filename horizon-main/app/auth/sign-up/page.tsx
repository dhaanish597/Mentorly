'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Loader2 } from 'lucide-react'
import { AuthShell, Field, PasswordInput } from '@/components/auth/auth-shell'
import { fieldClass, primaryBtn } from '@/components/ui-kit'
import { useStore } from '@/lib/store'

export default function SignUpPage() {
  const { signUp } = useStore()
  const router = useRouter()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    const next: Record<string, string> = {}
    if (name.trim().length < 2) next.name = 'Tell us what to call you.'
    if (!/^\S+@\S+\.\S+$/.test(email)) next.email = 'Enter a valid email address.'
    if (password.length < 8) next.password = 'Use at least 8 characters.'
    if (confirm !== password) next.confirm = 'Passwords do not match.'
    setErrors(next)
    if (Object.keys(next).length) return
    setBusy(true)
    const res = await signUp(name, email, password)
    setBusy(false)
    if (res.error) setErrors({ form: res.error })
    else router.replace('/home')
  }

  return (
    <AuthShell
      title="Start thinking out loud"
      subtitle="Create your account and meet the mentor who only asks questions."
      footer={
        <>
          Already have an account?{' '}
          <Link href="/auth/login" className="font-semibold text-plum underline underline-offset-4">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-5" noValidate>
        {errors.form && (
          <p role="alert" className="rounded-xl bg-destructive/10 px-3.5 py-2.5 text-sm text-destructive">
            {errors.form}
          </p>
        )}
        <Field id="name" label="Name" error={errors.name}>
          <input id="name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} className={fieldClass} aria-invalid={!!errors.name} aria-describedby={errors.name ? 'name-error' : undefined} />
        </Field>
        <Field id="email" label="Email" error={errors.email}>
          <input id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} className={fieldClass} aria-invalid={!!errors.email} aria-describedby={errors.email ? 'email-error' : undefined} />
        </Field>
        <Field id="password" label="Password" error={errors.password}>
          <PasswordInput id="password" value={password} onChange={setPassword} autoComplete="new-password" invalid={!!errors.password} />
        </Field>
        <Field id="confirm" label="Confirm password" error={errors.confirm}>
          <PasswordInput id="confirm" value={confirm} onChange={setConfirm} autoComplete="new-password" invalid={!!errors.confirm} />
        </Field>
        <button type="submit" disabled={busy} className={`${primaryBtn} w-full`}>
          {busy && <Loader2 className="size-4 animate-spin" />}
          Create account
        </button>
      </form>
    </AuthShell>
  )
}
