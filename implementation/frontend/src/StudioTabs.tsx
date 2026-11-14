import { useId } from 'react';
import type { ReactNode } from 'react';

type Tab<T extends string> = { id: T; label: string };
type Props<T extends string> = {
  label: string; tabs: readonly Tab<T>[]; value: T;
  onChange: (value: T) => void; children: ReactNode;
};

export function StudioTabs<T extends string>({ label, tabs, value, onChange, children }: Props<T>) {
  const prefix = useId();
  return <>
    <div role="tablist" aria-label={label} tabIndex={-1} className="studio-tabs" onKeyDown={event => {
      const index = tabs.findIndex(tab => tab.id === value);
      const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length
        : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length
        : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : -1;
      if (next < 0) return;
      event.preventDefault();
      onChange(tabs[next].id);
      document.getElementById(`${prefix}-tab-${tabs[next].id}`)?.focus();
    }}>
      {tabs.map(tab => <button type="button" role="tab" key={tab.id}
        id={`${prefix}-tab-${tab.id}`} aria-controls={`${prefix}-panel`}
        aria-selected={value === tab.id} tabIndex={value === tab.id ? 0 : -1}
        onClick={() => onChange(tab.id)}>{tab.label}</button>)}
    </div>
    <div role="tabpanel" id={`${prefix}-panel`} aria-labelledby={`${prefix}-tab-${value}`} tabIndex={0}>
      {children}
    </div>
  </>;
}
