import type { ReactNode } from 'react';

/** Nothing here yet: say so, and offer the one thing to do about it. */
export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      {hint && <p className="muted">{hint}</p>}
      {action}
    </div>
  );
}
