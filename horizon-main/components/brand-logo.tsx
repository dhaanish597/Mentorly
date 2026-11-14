import Link from 'next/link'
import { cn } from '@/lib/utils'

export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn('size-8', className)} aria-hidden="true">
      <rect width="32" height="32" rx="10" fill="#ff735c" />
      <path d="M7 22V10.5L16 19l9-8.5V22" fill="none" stroke="#24152f" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function BrandLogo({ href = '/', tone = 'dark', className }: { href?: string; tone?: 'dark' | 'light'; className?: string }) {
  return (
    <Link href={href} className={cn('inline-flex items-center gap-2.5 rounded-lg focus-visible:ring-3 focus-visible:ring-lavender/50 focus-visible:outline-none', className)}>
      <BrandMark />
      <span className={cn('font-heading text-xl font-semibold tracking-tight', tone === 'dark' ? 'text-plum' : 'text-ivory')}>Mentorly</span>
    </Link>
  )
}
