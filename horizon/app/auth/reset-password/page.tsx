'use client'

import { Suspense, useState } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Loader2 } from 'lucide-react'
import { AuthShell, Field, PasswordInput } from '@/components/auth/auth-shell'
import { primaryBtn } from '@/components/ui-kit'
import { useStore } from '@/lib/store'

function ResetForm() {
  const params = useSearchParams()
  const router = useRouter()
  const { resetPassword, pushToast } = useStore()
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const email = params.get('email') ?? ''
  const token = params.get('token') ?? ''

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    const next: Record<string, string> = {}
    if (password.length < 8) next.password = 'Use at least 8 characters.'
    if (confirm !== password) next.confirm = 'Passwords do not match.'
    setErrors(next)
    if (Object.keys(next).length) return
    setBusy(true)
    const res = await resetPassword(email, token, password)
    setBusy(false)
    if (res.error) return setErrors({ form: res.error })
    pushToast('Password updated. Please sign in.', 'success')
    router.replace('/auth/login')
  }

  if (!email || !token)
    return (
      <p role="alert" className="rounded-xl bg-destructive/10 px-3.5 py-3 text-sm text-destructive">
        This reset link is missing information.{' '}
        <Link href="/auth/forgot-password" className="font-semibold underline underline-offset-4">
          Request a new one
        </Link>
        .
      </p>
    )

  return (
    <form onSubmit={onSubmit} className="space-y-5" noValidate>
      {errors.form && (
        <p role="alert" className="rounded-xl bg-destructive/10 px-3.5 py-2.5 text-sm text-destructive">
          {errors.form}
        </p>
      )}
      <Field id="password" label="New password" error={errors.password}>
        <PasswordInput id="password" value={password} onChange={setPassword} autoComplete="new-password" invalid={!!errors.password} />
      </Field>
      <Field id="confirm" label="Confirm new password" error={errors.confirm}>
        <PasswordInput id="confirm" value={confirm} onChange={setConfirm} autoComplete="new-password" invalid={!!errors.confirm} />
      </Field>
      <button type="submit" disabled={busy} className={`${primaryBtn} w-full`}>
        {busy && <Loader2 className="size-4 animate-spin" />}
        Update password
      </button>
    </form>
  )
}

export default function ResetPasswordPage() {
  return (
    <AuthShell
      title="Choose a new password"
      subtitle="Make it at least 8 characters. You will use it to sign in next time."
      footer={
        <Link href="/auth/login" className="font-semibold text-plum underline underline-offset-4">
          Back to sign in
        </Link>
      }
    >
      <Suspense fallback={null}>
        <ResetForm />
      </Suspense>
    </AuthShell>
  )
}
