'use client'

import { useMemo } from 'react'
import { cn } from '@/lib/utils'

export type MentorState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'encouraging' | 'celebrating'

const BODY_ANIMATION: Record<MentorState, string> = {
  idle: 'mentor-breathe 4.2s ease-in-out infinite',
  listening: 'mentor-listen 2.6s ease-in-out infinite',
  thinking: 'mentor-think 3s ease-in-out infinite',
  speaking: 'mentor-speak 0.9s ease-in-out infinite',
  encouraging: 'mentor-nod 1.1s ease-in-out 2',
  celebrating: 'mentor-cheer 0.8s ease-in-out infinite',
}

export const STATE_LABEL: Record<MentorState, string> = {
  idle: 'Ready when you are',
  listening: 'Listening',
  thinking: 'Thinking',
  speaking: 'Speaking',
  encouraging: 'Nice thinking',
  celebrating: 'Challenge complete',
}

const CONFETTI_COLORS = ['#ff735c', '#b9e4d0', '#8c78b8', '#24152f', '#e8b04a']

export function DoodleMentor({ state, className }: { state: MentorState; className?: string }) {
  const confetti = useMemo(
    () =>
      Array.from({ length: 22 }, (_, i) => ({
        id: i,
        left: 18 + ((i * 37) % 64),
        dx: ((i * 53) % 160) - 80,
        dy: 120 + ((i * 29) % 140),
        rot: ((i * 71) % 520) - 260,
        delay: (i % 7) * 70,
        color: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
        round: i % 3 === 0,
      })),
    [],
  )

  return (
    <div
      className={cn('relative isolate aspect-[800/672] w-full select-none', className)}
      role="img"
      aria-label={`Mentor illustration. State: ${STATE_LABEL[state]}`}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/mentor/mentor.png"
        alt=""
        width={800}
        height={672}
        draggable={false}
        className="absolute inset-0 h-full w-full origin-bottom object-contain"
        style={{ animation: BODY_ANIMATION[state] }}
      />

      {state === 'listening' && (
        <div className="pointer-events-none absolute" style={{ left: '62%', top: '30%', width: '16%', height: '30%' }}>
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className="absolute inset-0 rounded-full border-2 border-coral"
              style={{ animationName: 'ring-out', animationDuration: '1.8s', animationTimingFunction: 'ease-out', animationIterationCount: 'infinite', animationDelay: `${i * 0.55}s` }}
            />
          ))}
        </div>
      )}

      {state === 'thinking' && (
        <div className="pointer-events-none absolute flex items-end gap-1.5 rounded-full border-2 border-plum bg-ivory px-3 py-2" style={{ left: '70%', top: '2%' }}>
          {[0, 1, 2].map((i) => (
            <span key={i} className="size-2 rounded-full bg-plum" style={{ animationName: 'dot-float', animationDuration: '1.2s', animationTimingFunction: 'ease-in-out', animationIterationCount: 'infinite', animationDelay: `${i * 0.18}s` }} />
          ))}
        </div>
      )}

      {state === 'speaking' && (
        <svg className="pointer-events-none absolute" style={{ left: '76%', top: '28%', width: '20%', height: '34%' }} viewBox="0 0 60 80" fill="none" aria-hidden="true">
          {[0, 1, 2].map((i) => (
            <path
              key={i}
              d={`M${10 + i * 14} ${22 - i * 5} Q ${24 + i * 14} 40 ${10 + i * 14} ${58 + i * 5}`}
              stroke="#ff735c"
              strokeWidth="4"
              strokeLinecap="round"
              style={{ animationName: 'dot-float', animationDuration: '0.9s', animationTimingFunction: 'ease-in-out', animationIterationCount: 'infinite', animationDelay: `${i * 0.15}s` }}
            />
          ))}
        </svg>
      )}

      {state === 'encouraging' && (
        <svg className="pointer-events-none absolute" style={{ left: '72%', top: '4%', width: '16%', animation: 'pop-in 0.5s ease-out both' }} viewBox="0 0 40 40" aria-hidden="true">
          <path d="M20 3 L24 15 L37 16 L27 24 L30 37 L20 30 L10 37 L13 24 L3 16 L16 15 Z" fill="#ff735c" stroke="#24152f" strokeWidth="2.5" strokeLinejoin="round" />
        </svg>
      )}

      {state === 'celebrating' && (
        <div className="pointer-events-none absolute inset-x-0 top-0 h-full overflow-visible" aria-hidden="true">
          {confetti.map((c) => (
            <span
              key={c.id}
              className={cn('absolute top-[6%] block h-2.5 w-1.5', c.round && 'size-2 rounded-full')}
              style={
                {
                  left: `${c.left}%`,
                  background: c.color,
                  '--dx': `${c.dx}px`,
                  '--dy': `${c.dy}px`,
                  '--rot': `${c.rot}deg`,
                  animationName: 'confetti-fall',
                  animationDuration: '1.6s',
                  animationTimingFunction: 'ease-out',
                  animationIterationCount: 'infinite',
                  animationDelay: `${c.delay}ms`,
                } as React.CSSProperties
              }
            />
          ))}
        </div>
      )}
    </div>
  )
}

export function Equalizer({ active, className }: { active: boolean; className?: string }) {
  return (
    <span className={cn('inline-flex h-4 items-end gap-0.5', className)} aria-hidden="true">
      {[0, 1, 2, 3].map((i) => (
        <span
          key={i}
          className="block h-full w-1 origin-bottom rounded-full bg-current"
          style={{ transform: active ? undefined : 'scaleY(0.25)', animationName: active ? 'eq-bar' : undefined, animationDuration: `${0.7 + i * 0.12}s`, animationTimingFunction: 'ease-in-out', animationIterationCount: 'infinite', animationDelay: `${i * 0.1}s` }}
        />
      ))}
    </span>
  )
}
