'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Loader2 } from 'lucide-react'
import { AuthShell, Field, PasswordInput } from '@/components/auth/auth-shell'
import { fieldClass, primaryBtn } from '@/components/ui-kit'
import { useStore } from '@/lib/store'

export default function LoginPage() {
  const { signIn } = useStore()
  const router = useRouter()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<{ email?: string; password?: string; form?: string }>({})
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    const next: typeof errors = {}
    if (!/^\S+@\S+\.\S+$/.test(email)) next.email = 'Enter a valid email address.'
    if (!password) next.password = 'Enter your password.'
    setErrors(next)
    if (Object.keys(next).length) return
    setBusy(true)
    const res = await signIn(email, password)
    setBusy(false)
    if (res.error) setErrors({ form: res.error })
    else router.replace('/home')
  }

  return (
    <AuthShell
      title="Welcome back"
      subtitle="Pick up where your last conversation with your mentor left off."
      footer={
        <>
          New to Mentorly?{' '}
          <Link href="/auth/sign-up" className="font-semibold text-plum underline underline-offset-4">
            Create an account
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
        <Field id="email" label="Email" error={errors.email}>
          <input id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} className={fieldClass} aria-invalid={!!errors.email} aria-describedby={errors.email ? 'email-error' : undefined} />
        </Field>
        <Field id="password" label="Password" error={errors.password}>
          <PasswordInput id="password" value={password} onChange={setPassword} autoComplete="current-password" invalid={!!errors.password} />
        </Field>
        <div className="flex justify-end">
          <Link href="/auth/forgot-password" className="text-sm font-medium text-plum underline underline-offset-4">
            Forgot password?
          </Link>
        </div>
        <button type="submit" disabled={busy} className={`${primaryBtn} w-full`}>
          {busy && <Loader2 className="size-4 animate-spin" />}
          Sign in
        </button>
      </form>
    </AuthShell>
  )
}
