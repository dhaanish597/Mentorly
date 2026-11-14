'use client'

import { useEffect } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { Flame, Home, LineChart, LogOut, Map, MessagesSquare, UserRound, Loader2 } from 'lucide-react'
import { BrandLogo } from '@/components/brand-logo'
import { ProgressBar } from '@/components/ui-kit'
import { levelForXp } from '@/lib/gamification'
import { useStore } from '@/lib/store'
import { cn } from '@/lib/utils'

const NAV = [
  { href: '/home', label: 'Home', icon: Home },
  { href: '/paths', label: 'Learning Paths', short: 'Paths', icon: Map },
  { href: '/practice', label: 'Practice Arena', short: 'Practice', icon: MessagesSquare },
  { href: '/progress', label: 'My Progress', short: 'Progress', icon: LineChart },
  { href: '/profile', label: 'Profile', icon: UserRound },
]

export function AppShell({ children }: { children: React.ReactNode }) {
  const { ready, user, state, signOut } = useStore()
  const pathname = usePathname()
  const router = useRouter()

  useEffect(() => {
    if (ready && !user) router.replace('/auth/login')
  }, [ready, user, router])

  if (!ready || !user)
    return (
      <div className="grid min-h-dvh place-items-center bg-background" role="status">
        <Loader2 className="size-6 animate-spin text-coral" />
        <span className="sr-only">Loading your workspace</span>
      </div>
    )

  const lvl = levelForXp(state.xp)
  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`)

  return (
    <div className="flex min-h-dvh flex-col lg:flex-row">
      <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col bg-sidebar p-5 text-sidebar-foreground lg:flex">
        <BrandLogo href="/home" tone="light" className="px-1" />
        <nav className="mt-10 flex flex-1 flex-col gap-1" aria-label="Main">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive(item.href) ? 'page' : undefined}
              className={cn(
                'flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition focus-visible:ring-3 focus-visible:ring-lavender/60 focus-visible:outline-none',
                isActive(item.href) ? 'bg-sidebar-accent text-white' : 'text-sidebar-foreground/75 hover:bg-sidebar-accent/60 hover:text-white',
              )}
            >
              <item.icon className={cn('size-4.5', isActive(item.href) && 'text-coral')} />
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="space-y-4 rounded-2xl bg-sidebar-accent p-4">
          <div className="flex items-center justify-between text-xs">
            <span className="font-semibold text-white">Level {lvl.level}</span>
            <span className="flex items-center gap-1 text-coral">
              <Flame className="size-3.5" /> {state.streak} day{state.streak === 1 ? '' : 's'}
            </span>
          </div>
          <div>
            <ProgressBar value={lvl.progress} tone="coral" className="bg-plum" />
            <p className="mt-2 text-xs text-sidebar-foreground/70">
              {state.xp} XP &middot; {lvl.toNext} to level {lvl.level + 1}
            </p>
          </div>
        </div>

        <div className="mt-4 flex items-center gap-3 px-1">
          <div className="grid size-9 shrink-0 place-items-center rounded-full bg-coral text-sm font-bold text-plum">{user.name.charAt(0).toUpperCase()}</div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-white">{user.name}</p>
            <p className="truncate text-xs text-sidebar-foreground/60">{lvl.title}</p>
          </div>
          <button
            type="button"
            aria-label="Sign out"
            onClick={() => {
              signOut()
              router.replace('/')
            }}
            className="rounded-lg p-2 text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-white"
          >
            <LogOut className="size-4" />
          </button>
        </div>
      </aside>

      <header className="sticky top-0 z-30 flex items-center justify-between bg-sidebar px-4 py-3 lg:hidden">
        <BrandLogo href="/home" tone="light" />
        <div className="flex items-center gap-3 text-xs text-white">
          <span className="flex items-center gap-1 text-coral">
            <Flame className="size-3.5" /> {state.streak}
          </span>
          <span className="rounded-full bg-sidebar-accent px-2.5 py-1 font-semibold">{state.xp} XP</span>
        </div>
      </header>

      <main className="min-w-0 flex-1 pb-20 lg:pb-0">{children}</main>

      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-sidebar-border bg-sidebar px-1 py-1.5 lg:hidden" aria-label="Main">
        {NAV.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            aria-current={isActive(item.href) ? 'page' : undefined}
            className={cn('flex flex-col items-center gap-1 rounded-lg py-1.5 text-[11px] font-medium', isActive(item.href) ? 'text-coral' : 'text-sidebar-foreground/70')}
          >
            <item.icon className="size-5" />
            {item.short ?? item.label}
          </Link>
        ))}
      </nav>
    </div>
  )
}

export function Page({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn('mx-auto w-full max-w-6xl space-y-8 px-4 py-6 sm:px-8 sm:py-10', className)}>{children}</div>
}
