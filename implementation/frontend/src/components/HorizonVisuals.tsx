import type { ReactNode } from 'react';
import { FALLBACK_BRANDING } from '../config/branding';

import { TEACHERS, type TeacherConfig, type TeacherId } from '../config/teachers';

export type IconName = 'home' | 'code' | 'paths' | 'progress' | 'design' | 'mic' | 'arrow' | 'settings' | 'book' | 'check' | 'flame' | 'award' | 'zap' | 'star' | 'rocket' | 'compass' | 'shield' | 'clock' | 'target' | 'refresh';
const paths: Record<IconName, ReactNode> = {
  home: <><path d="m3 10 9-7 9 7v10H3Z"/><path d="M9 20v-7h6v7"/></>,
  code: <path d="m8 7-5 5 5 5m8-10 5 5-5 5m-3-13-2 20"/>,
  paths: <><path d="M6 3v6a3 3 0 0 0 3 3h6a3 3 0 0 1 3 3v6"/><circle cx="6" cy="3" r="2"/><circle cx="18" cy="21" r="2"/></>,
  progress: <path d="M4 19V5m0 14h16M8 15l4-5 4 2 4-7"/>,
  design: <><rect x="3" y="3" width="7" height="6" rx="1"/><rect x="14" y="15" width="7" height="6" rx="1"/><path d="M6 9v9h8m-4-12h8v9"/></>,
  mic: <><rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2m-7 9v3m-4 0h8"/></>,
  arrow: <path d="M4 12h16m-6-6 6 6-6 6"/>,
  settings: <><path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/></>,
  book: <><path d="M12 5C8 2 4 3 2 4v15c3-1 7-1 10 1 3-2 7-2 10-1V4c-3-1-7-2-10 1Z"/><path d="M12 5v15"/></>,
  check: <><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></>,
  flame: <path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>,
  award: <><circle cx="12" cy="8" r="6"/><path d="M15.477 12.89 17 22l-5-3-5 3 1.523-9.11"/></>,
  zap: <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>,
  star: <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>,
  rocket: <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09zM12 15l-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/>,
  compass: <><circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/></>,
  shield: <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>,
  clock: <><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></>,
  target: <><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></>,
  refresh: <><path d="M21.5 2v6h-6M2.5 22v-6h6"/><path d="M19.07 15.57A8 8 0 0 1 5 19.5L2.5 16M4.93 8.43A8 8 0 0 1 19 4.5L21.5 8"/></>,
};
export function Icon({ name, className = '' }: { name: IconName; className?: string }) {
  return <svg className={`horizon-icon ${className}`} viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] ?? paths.code}</svg>;
}
export function BrandLogo({ href = '/', compact = false, onNavigate }: { href?: string; compact?: boolean; onNavigate?: (href: string) => void }) {
  const handleClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    if (onNavigate && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey && e.button === 0) {
      e.preventDefault();
      onNavigate(href);
    }
  };
  return <a href={href} onClick={handleClick} className="horizon-brand"><span className="horizon-brand-mark"><Icon name="mic" /></span>{!compact && <strong>{FALLBACK_BRANDING.productName}</strong>}</a>;
}
export function MentorPortrait({
  state = 'idle',
  className = '',
  eager = false,
  teacher = 'astra',
  alt,
}: {
  state?: 'idle' | 'listening' | 'thinking' | 'speaking';
  className?: string;
  eager?: boolean;
  teacher?: TeacherId | TeacherConfig;
  alt?: string;
}) {
  const teacherConfig = typeof teacher === 'string' ? (TEACHERS[teacher] ?? TEACHERS.astra) : teacher;
  const defaultAlt = teacherConfig.id === 'astra' ? `Your ${FALLBACK_BRANDING.productName} mentor` : `Your mentor: ${teacherConfig.name} (${teacherConfig.subject})`;
  return (
    <div className={`mentor-portrait mentor-${state} ${className}`} data-teacher={teacherConfig.id}>
      <img
        src={teacherConfig.avatarUrl}
        alt={alt ?? defaultAlt}
        width="800"
        height="672"
        loading={eager ? 'eager' : 'lazy'}
        draggable={false}
      />
    </div>
  );
}
