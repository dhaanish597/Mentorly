'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Eye, EyeOff, Info } from 'lucide-react'
import { BrandLogo } from '@/components/brand-logo'
import { DoodleMentor } from '@/components/mentor/doodle-mentor'
import { fieldClass } from '@/components/ui-kit'
import { useStore } from '@/lib/store'

export function AuthShell({ title, subtitle, children, footer }: { title: string; subtitle: string; children: React.ReactNode; footer: React.ReactNode }) {
  const { ready, user } = useStore()
  const router = useRouter()

  useEffect(() => {
    if (ready && user) router.replace('/home')
  }, [ready, user, router])

  return (
    <div className="grid min-h-dvh lg:grid-cols-[1.05fr_1fr]">
      <aside className="paper-grain relative hidden flex-col justify-between overflow-hidden bg-plum p-10 text-ivory lg:flex">
        <BrandLogo tone="light" />
        <div className="mx-auto w-full max-w-md">
          <div className="rounded-[2rem] bg-ivory p-6 pb-2">
            <DoodleMentor state="thinking" />
          </div>
          <blockquote className="mt-8">
            <p className="font-heading text-3xl leading-snug text-balance italic">&ldquo;It only asks you questions.&rdquo;</p>
            <p className="mt-3 text-sm text-ivory/70">Mentorly never hands you the answer. It teaches you to find it, and to explain how.</p>
          </blockquote>
        </div>
        <p className="text-xs text-ivory/50">Think. Explain. Solve. Grow.</p>
      </aside>

      <main className="flex flex-col px-6 py-8 sm:px-10">
        <div className="lg:hidden">
          <BrandLogo />
        </div>
        <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center py-10">
          <h1 className="font-heading text-3xl font-semibold text-balance text-plum">{title}</h1>
          <p className="mt-2 text-muted-foreground">{subtitle}</p>
          <div className="mt-8">{children}</div>
          <div className="mt-6 text-center text-sm text-muted-foreground">{footer}</div>
          <p className="mt-8 flex items-start gap-2 rounded-xl bg-lavender-soft/60 px-3 py-2.5 text-xs text-plum/80">
            <Info className="mt-0.5 size-3.5 shrink-0" />
            Demo mode: accounts and progress are stored in this browser only until the backend is connected.
          </p>
        </div>
      </main>
    </div>
  )
}

export function Field({ id, label, error, children }: { id: string; label: string; error?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-sm font-medium text-plum">
        {label}
      </label>
      {children}
      {error && (
        <p id={`${id}-error`} role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}

export function PasswordInput({ id, value, onChange, autoComplete, invalid }: { id: string; value: string; onChange: (v: string) => void; autoComplete: string; invalid?: boolean }) {
  const [shown, setShown] = useState(false)
  return (
    <div className="relative">
      <input
        id={id}
        type={shown ? 'text' : 'password'}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        aria-invalid={invalid}
        aria-describedby={invalid ? `${id}-error` : undefined}
        className={`${fieldClass} pr-11`}
      />
      <button
        type="button"
        onClick={() => setShown((s) => !s)}
        aria-label={shown ? 'Hide password' : 'Show password'}
        className="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-muted-foreground hover:text-plum"
      >
        {shown ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </div>
  )
}
