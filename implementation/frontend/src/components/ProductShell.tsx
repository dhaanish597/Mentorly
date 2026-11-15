import { useEffect, useState } from 'react';
import type { ReactNode, MouseEvent } from 'react';
import { BrandLogo, Icon, type IconName } from './HorizonVisuals';

const links: { href: string; label: string; icon: IconName }[] = [
  { href: '/dashboard', label: 'Home', icon: 'home' },
  { href: '/library', label: 'Practice', icon: 'code' },
  { href: '/learn', label: 'Learn', icon: 'paths' },
  { href: '/studio', label: 'Design studio', icon: 'design' },
  { href: '/interviews', label: 'Interviews', icon: 'mic' },
  { href: '/progress', label: 'Progress', icon: 'progress' },
];

export function navigate(href: string): void {
  if (typeof window === 'undefined' || !href) return;
  const current = window.location.pathname + window.location.search;
  if (current === href) return;
  window.history.pushState({}, '', href);
  window.dispatchEvent(new PopStateEvent('popstate'));
  window.scrollTo({ top: 0, behavior: 'instant' });
}

export function ProductShell({ children, current, workspace = false }: { children: ReactNode; current: string; workspace?: boolean }) {
  const [questionOpen, setQuestionOpen] = useState(() => location.pathname.startsWith('/practice/'));
  useEffect(() => {
    const update = () => setQuestionOpen(location.pathname.startsWith('/practice/'));
    window.addEventListener('popstate', update);
    window.addEventListener('viva:route-change', update);
    return () => { window.removeEventListener('popstate', update); window.removeEventListener('viva:route-change', update); };
  }, []);
  const active = current.startsWith('/practice/') ? '/library' : current.startsWith('/studio') ? '/studio' : current.startsWith('/learn') || current.startsWith('/paths') ? '/learn' : current;

  const handleNav = (e: MouseEvent<HTMLAnchorElement>, href: string) => {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
    e.preventDefault();
    navigate(href);
  };

  return (
    <div className={`product-shell ${workspace ? 'product-workspace' : ''} ${questionOpen ? 'question-workspace' : ''}`}>
      <a className="product-skip-link" href={workspace ? current.startsWith('/studio') ? '#studio-main' : '#main-content' : '#product-main'}>Skip to content</a>
      <aside className="product-sidebar">
        <BrandLogo href="/dashboard" compact={questionOpen} onNavigate={navigate} />
        <nav aria-label="Main navigation">
          {links.map(link => (
            <a
              href={link.href}
              key={link.href}
              aria-label={link.label}
              title={link.label}
              aria-current={active === link.href ? 'page' : undefined}
              onClick={e => handleNav(e, link.href)}
            >
              <Icon name={link.icon} />
              <span>{link.label}</span>
            </a>
          ))}
        </nav>
        <div className="sidebar-note">
          <span className="sidebar-voice-dot" />
          <strong>Think. Explain. Grow.</strong>
          <p>One thoughtful conversation at a time.</p>
        </div>
        <a
          className="sidebar-settings"
          aria-label="Settings"
          title="Settings"
          href="/settings"
          aria-current={current === '/settings' ? 'page' : undefined}
          onClick={e => handleNav(e, '/settings')}
        >
          <Icon name="settings" />
          <span>Settings</span>
        </a>
      </aside>
      <div className="product-mobile-header">
        <BrandLogo href="/dashboard" onNavigate={navigate} />
        <a
          href="/settings"
          aria-label="Workspace settings"
          onClick={e => handleNav(e, '/settings')}
        >
          <Icon name="settings" />
        </a>
      </div>
      {workspace ? <div className="product-workspace-content">{children}</div> : <main id="product-main" className="product-main">{children}</main>}
      <nav className="product-mobile-nav" aria-label="Quick navigation">
        {links.map(link => (
          <a
            key={link.href}
            href={link.href}
            aria-current={active === link.href ? 'page' : undefined}
            aria-label={`Go to ${link.label}`}
            onClick={e => handleNav(e, link.href)}
          >
            <Icon name={link.icon} />
            <span>
              {link.label === 'Design studio'
                ? 'Studio'
                : link.label}
            </span>
          </a>
        ))}
      </nav>
    </div>
  );
}
