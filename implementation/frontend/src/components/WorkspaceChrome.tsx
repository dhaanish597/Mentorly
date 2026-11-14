import { useEffect, useRef } from 'react';
import type { KeyboardEvent, PointerEvent, ReactNode } from 'react';

type ResizeProps = { label: string; value: number; min: number; max: number; defaultValue: number; orientation: 'horizontal' | 'vertical'; reverse?: boolean; onChange: (value: number) => void };
export function ResizeHandle({ label, value, min, max, defaultValue, orientation, reverse = false, onChange }: ResizeProps) {
  const start = useRef<{ point: number; value: number } | null>(null);
  const limit = (next: number) => Math.max(min, Math.min(max, next));
  function key(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key === 'Home' || event.key === 'Enter') { event.preventDefault(); onChange(defaultValue); return; }
    const negative = orientation === 'vertical' ? 'ArrowLeft' : 'ArrowUp';
    const positive = orientation === 'vertical' ? 'ArrowRight' : 'ArrowDown';
    if (event.key !== negative && event.key !== positive) return;
    event.preventDefault(); onChange(limit(value + (event.key === positive ? 20 : -20) * (reverse ? -1 : 1)));
  }
  function move(event: PointerEvent<HTMLDivElement>): void {
    if (!start.current) return;
    const point = orientation === 'vertical' ? event.clientX : event.clientY;
    onChange(limit(start.current.value + (point - start.current.point) * (reverse ? -1 : 1)));
  }
  // WAI-ARIA window splitters are focusable separators with arrow-key value adjustment.
  // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex -- Intentional accessible window-splitter pattern.
  return <div className={`resize-handle resize-${orientation}`} role="separator" tabIndex={0} aria-label={label} aria-orientation={orientation} aria-valuemin={min} aria-valuemax={max} aria-valuenow={value} aria-valuetext={`${Math.round(value)} pixels. Arrow keys resize; Home resets.`} onKeyDown={key} onDoubleClick={() => onChange(defaultValue)} onPointerDown={e => { start.current = { point: orientation === 'vertical' ? e.clientX : e.clientY, value }; e.currentTarget.setPointerCapture(e.pointerId); }} onPointerMove={move} onPointerUp={() => { start.current = null; }} onPointerCancel={() => { start.current = null; }} />;
}
export function AccessibleTabs({ label, tabs, selected, onSelect, controls }: { label: string; tabs: string[]; selected: string; onSelect: (tab: string) => void; controls?: Record<string, string> }) {
  function key(event: KeyboardEvent<HTMLButtonElement>, index: number): void {
    const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null;
    if (next === null) return;
    event.preventDefault(); onSelect(tabs[next]);
    const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role=tab]');
    buttons?.[next].focus();
  }
  return <div className="pane-tabs" role="tablist" aria-label={label}>{tabs.map((tab, index) => <button type="button" key={tab} id={controls?.[tab] ? `${controls[tab]}-tab` : undefined} role="tab" aria-controls={controls?.[tab]} aria-selected={selected === tab} tabIndex={selected === tab ? 0 : -1} onClick={() => onSelect(tab)} onKeyDown={e => key(e, index)}>{tab}</button>)}</div>;
}
export function SettingsDialog({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  const dialog = useRef<HTMLDivElement | null>(null);
  const close = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    close.current?.focus();
    return () => { previous?.focus(); };
  }, []);
  function key(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key === 'Escape') { event.preventDefault(); onClose(); return; }
    if (event.key !== 'Tab') return;
    const controls = [...(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary,[tabindex="0"]') ?? [])];
    const first = controls[0]; const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }
  // The dialog handles Escape/Tab; dismissal also has an explicit focusable Close button.
  // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- The dialog root owns keyboard focus trapping.
  return <div className="dialog-backdrop" role="presentation" onClick={event => { if (event.target === event.currentTarget) onClose(); }}><div className="settings-dialog" role="dialog" tabIndex={-1} aria-modal="true" aria-labelledby="settings-title" onKeyDown={key} ref={dialog}><div className="settings-heading"><h2 id="settings-title">Workspace settings</h2><button type="button" ref={close} onClick={onClose} aria-label="Close settings">Close</button></div>{children}</div></div>;
}
export function WorkspaceHeader({ productName, shortName, title, onLibrary, onSettings, onToggleCoach, collapsed, isLibrary }: { productName: string; shortName: string; title?: string; onLibrary: () => void; onSettings: () => void; onToggleCoach: () => void; collapsed: boolean; isLibrary: boolean }) {
  return <header className="workspace-header"><a className="wordmark" href="/library" onClick={event => { event.preventDefault(); onLibrary(); }} aria-label={`${productName} library`}><span className="brand-mark" aria-hidden="true">{shortName}</span><strong>{productName}</strong></a><nav aria-label="Main navigation"><a href="/dashboard">Home</a><a href="/paths">Learning paths</a><a href="/progress">Progress</a><button type="button" aria-current={isLibrary ? 'page' : undefined} onClick={onLibrary}>Problem library</button>{!isLibrary && <span className="header-problem">{title}</span>}</nav><div className="header-actions">{!isLibrary && <button type="button" aria-expanded={!collapsed} onClick={onToggleCoach}>{collapsed ? 'Show coach' : 'Hide coach'}</button>}<button type="button" onClick={onSettings}>Settings</button></div></header>;
}
