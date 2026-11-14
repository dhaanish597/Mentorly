'use client'

import { useState } from 'react'
import Link from 'next/link'
import { Loader2, MailCheck } from 'lucide-react'
import { AuthShell, Field } from '@/components/auth/auth-shell'
import { fieldClass, primaryBtn } from '@/components/ui-kit'
import { useStore } from '@/lib/store'

export default function ForgotPasswordPage() {
  const { requestPasswordReset } = useStore()
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState<{ token?: string } | null>(null)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!/^\S+@\S+\.\S+$/.test(email)) return setError('Enter a valid email address.')
    setError('')
    setBusy(true)
    setSent(await requestPasswordReset(email))
    setBusy(false)
  }

  return (
    <AuthShell
      title="Reset your password"
      subtitle="Enter your email and we will send you a link to choose a new password."
      footer={
        <Link href="/auth/login" className="font-semibold text-plum underline underline-offset-4">
          Back to sign in
        </Link>
      }
    >
      {sent ? (
        <div className="space-y-4 rounded-2xl border border-border bg-card p-5" role="status">
          <MailCheck className="size-6 text-mint-deep" />
          <p className="text-sm text-ink">If an account exists for {email}, a reset link is on its way.</p>
          {sent.token && (
            <div className="rounded-xl bg-lavender-soft/60 p-3 text-sm">
              <p className="mb-2 text-xs text-plum/80">Demo mode: email delivery is not connected yet, so use the link directly.</p>
              <Link href={`/auth/reset-password?email=${encodeURIComponent(email)}&token=${sent.token}`} className="font-semibold text-plum underline underline-offset-4">
                Open reset link
              </Link>
            </div>
          )}
        </div>
      ) : (
        <form onSubmit={onSubmit} className="space-y-5" noValidate>
          <Field id="email" label="Email" error={error}>
            <input id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} className={fieldClass} aria-invalid={!!error} aria-describedby={error ? 'email-error' : undefined} />
          </Field>
          <button type="submit" disabled={busy} className={`${primaryBtn} w-full`}>
            {busy && <Loader2 className="size-4 animate-spin" />}
            Send reset link
          </button>
        </form>
      )}
    </AuthShell>
  )
}
