'use client'

import { CheckCircle2, Info, Sparkles, X, AlertCircle } from 'lucide-react'
import { useStore } from '@/lib/store'
import { cn } from '@/lib/utils'

const TONE = {
  xp: { icon: Sparkles, cls: 'bg-plum text-ivory [&_svg]:text-coral' },
  info: { icon: Info, cls: 'bg-card text-ink border-border [&_svg]:text-lavender' },
  success: { icon: CheckCircle2, cls: 'bg-mint text-plum [&_svg]:text-plum' },
  error: { icon: AlertCircle, cls: 'bg-card text-destructive border-destructive/40' },
} as const

export function ToastHost() {
  const { toasts, dismissToast } = useStore()
  return (
    <div className="pointer-events-none fixed right-4 bottom-4 z-[100] flex w-[min(92vw,22rem)] flex-col gap-2" aria-live="polite">
      {toasts.map((t) => {
        const Tone = TONE[t.tone]
        return (
          <div
            key={t.id}
            className={cn('pointer-events-auto flex items-center gap-3 rounded-2xl border border-transparent px-4 py-3 text-sm font-medium shadow-lg', Tone.cls)}
            style={{ animation: 'slide-up 0.25s ease-out both' }}
          >
            <Tone.icon className="size-4 shrink-0" />
            <span className="flex-1">{t.text}</span>
            <button type="button" onClick={() => dismissToast(t.id)} aria-label="Dismiss notification" className="opacity-70 hover:opacity-100">
              <X className="size-4" />
            </button>
          </div>
        )
      })}
    </div>
  )
}
