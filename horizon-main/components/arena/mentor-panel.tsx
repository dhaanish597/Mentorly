'use client'

import { useEffect, useRef } from 'react'
import { Lightbulb, Mic, MicOff, SendHorizontal, Volume2, VolumeX } from 'lucide-react'
import { DoodleMentor, Equalizer, STATE_LABEL, type MentorState } from '@/components/mentor/doodle-mentor'
import { cn } from '@/lib/utils'

export interface ChatMessage {
  id: string
  role: 'mentor' | 'student' | 'system'
  text: string
}

interface Props {
  mentorState: MentorState
  messages: ChatMessage[]
  answerEnabled: boolean
  placeholder: string
  draft: string
  onDraft: (v: string) => void
  onSend: () => void
  listening: boolean
  supportsStt: boolean
  micError: string
  onToggleMic: () => void
  autoSpeak: boolean
  onToggleSpeak: () => void
  onHint: () => void
  hintsLeft: number
  speaking: boolean
}

export function MentorPanel(p: Props) {
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [p.messages.length])

  return (
    <section aria-label="Mentor conversation" className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-3xl border border-border bg-card">
      <div className="flex items-center gap-4 border-b border-border bg-ivory-deep/60 px-4 py-3">
        <div className="w-28 shrink-0 rounded-2xl bg-ivory px-1.5 pt-1.5 sm:w-32">
          <DoodleMentor state={p.mentorState} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="font-heading text-lg font-semibold text-plum">Your mentor</p>
          <p className="flex items-center gap-2 text-sm text-muted-foreground" aria-live="polite">
            {STATE_LABEL[p.mentorState]}
            <Equalizer active={p.speaking} />
          </p>
        </div>
        <button
          type="button"
          onClick={p.onToggleSpeak}
          aria-pressed={p.autoSpeak}
          aria-label={p.autoSpeak ? 'Mute mentor voice' : 'Unmute mentor voice'}
          className="grid size-10 place-items-center rounded-full border border-border bg-card text-plum hover:bg-ivory-deep focus-visible:ring-3 focus-visible:ring-lavender/50 focus-visible:outline-none"
        >
          {p.autoSpeak ? <Volume2 className="size-4" /> : <VolumeX className="size-4" />}
        </button>
      </div>

      <div className="min-h-48 flex-1 space-y-3 overflow-y-auto px-4 py-4 lg:min-h-0" role="log" aria-live="polite" aria-label="Conversation">
        {p.messages.map((m) =>
          m.role === 'system' ? (
            <p key={m.id} className="text-center text-xs text-muted-foreground">
              {m.text}
            </p>
          ) : (
            <div key={m.id} className={cn('flex', m.role === 'student' && 'justify-end')}>
              <p className={cn('max-w-[88%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed text-pretty', m.role === 'mentor' ? 'rounded-tl-md bg-lavender-soft text-plum' : 'rounded-tr-md bg-plum text-ivory')}>{m.text}</p>
            </div>
          ),
        )}
        <div ref={endRef} />
      </div>

      <div className="space-y-2 border-t border-border p-3">
        {p.micError && (
          <p role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {p.micError}
          </p>
        )}
        <div className="flex items-end gap-2">
          <textarea
            value={p.draft}
            onChange={(e) => p.onDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
                e.preventDefault()
                if (p.answerEnabled) p.onSend()
              }
            }}
            disabled={!p.answerEnabled}
            rows={2}
            aria-label="Your answer"
            placeholder={p.listening ? 'Listening... speak naturally' : p.placeholder}
            className="max-h-40 min-h-12 flex-1 resize-none rounded-xl border border-input bg-background px-3.5 py-2.5 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-lavender focus-visible:ring-3 focus-visible:ring-lavender/30 disabled:cursor-not-allowed disabled:opacity-60"
          />
          <div className="flex flex-col gap-2">
            <button
              type="button"
              onClick={p.onToggleMic}
              disabled={!p.answerEnabled || !p.supportsStt}
              aria-pressed={p.listening}
              aria-label={p.supportsStt ? (p.listening ? 'Stop recording' : 'Answer by voice') : 'Voice input not supported in this browser'}
              title={p.supportsStt ? undefined : 'Voice input is not supported in this browser'}
              className={cn('grid size-11 place-items-center rounded-xl border transition focus-visible:ring-3 focus-visible:ring-lavender/50 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50', p.listening ? 'animate-pulse border-coral bg-coral text-plum' : 'border-border bg-card text-plum hover:bg-ivory-deep')}
            >
              {p.supportsStt ? p.listening ? <MicOff className="size-4" /> : <Mic className="size-4" /> : <MicOff className="size-4" />}
            </button>
          </div>
          <button type="button" onClick={p.onSend} disabled={!p.answerEnabled || !p.draft.trim()} aria-label="Send answer" className="grid size-11 place-items-center rounded-xl bg-plum text-ivory transition hover:bg-plum-soft focus-visible:ring-3 focus-visible:ring-lavender/50 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-40">
            <SendHorizontal className="size-4" />
          </button>
        </div>
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <button type="button" onClick={p.onHint} className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 font-medium text-plum hover:bg-ivory-deep focus-visible:ring-3 focus-visible:ring-lavender/40 focus-visible:outline-none">
            <Lightbulb className="size-3.5 text-coral-deep" />
            Ask for a hint ({p.hintsLeft} left)
          </button>
          <span>{p.answerEnabled ? 'Enter to send' : 'Use the workspace for this step'}</span>
        </div>
      </div>
    </section>
  )
}
