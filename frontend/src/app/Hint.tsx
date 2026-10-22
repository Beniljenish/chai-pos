import { useState, type ReactNode } from 'react';
import { t } from '../lib/i18n';

/** Explanation that most people read once: a small ⓘ that opens it, so the screen stays about the data. */
export function Hint({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="hint">
      <button
        type="button"
        className="hint-btn"
        aria-expanded={open}
        aria-label={t('More info')}
        onClick={() => setOpen(!open)}
      >
        ⓘ
      </button>
      {open && (
        <p className="hint-text muted" role="note">
          {children}
        </p>
      )}
    </div>
  );
}
