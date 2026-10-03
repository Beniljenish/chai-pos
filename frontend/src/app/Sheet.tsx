/**
 * A bottom sheet on phones, a centred card on tablets. Escape or a tap outside closes it.
 * Every dialog in the app uses this one component (README, "Phase 5.4").
 */
import { useEffect, useId, useRef, type ReactNode } from 'react';

export function Sheet({
  title,
  label,
  sub,
  onClose,
  className,
  children,
}: {
  /** The heading. A string is also the dialog's accessible name. */
  title: ReactNode;
  /** The accessible name when `title` is not plain text. */
  label?: string;
  /** A line under the heading (on hand, current version...). */
  sub?: ReactNode;
  onClose(): void;
  className?: string;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLDivElement>(null);
  const headingId = useId();
  // Callers pass `onClose={() => ...}`, a new function on every render. The
  // effect below must not re-run for that: it would pull the focus out of the
  // box being typed in each time the screen behind refreshes (every 5 s on Tables).
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && close.current();
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      // Back to where the person was (keyboards and screen readers).
      if (opener?.isConnected) opener.focus({ preventScroll: true });
    };
  }, []);
  const named = typeof title === 'string' && !label;
  return (
    <div className="overlay" onClick={() => close.current()}>
      <div
        className={`sheet ${className ?? ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={named ? undefined : label}
        aria-labelledby={named ? headingId : undefined}
        tabIndex={-1}
        ref={dialog}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="sheet-head">
          <div>
            <h2 id={headingId}>{title}</h2>
            {sub}
          </div>
          <button className="quiet" onClick={() => close.current()}>
            Close
          </button>
        </header>
        {children}
      </div>
    </div>
  );
}
