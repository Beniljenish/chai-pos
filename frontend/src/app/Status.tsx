/**
 * The two states every screen that loads from the server can be in before it has
 * data: still loading, or the load failed. One look everywhere, and a failed load
 * can always be retried in place (README, "Phase 5.4").
 */
export function Loading({ what }: { what?: string }) {
  // Three shimmering rows where the content will be; the words are for screen
  // readers (and the tests that wait for them to go).
  return (
    <div className="skeleton" role="status">
      <span className="sr-only">Loading{what ? ` ${what}` : ''}…</span>
      <span className="skeleton-row" aria-hidden="true" />
      <span className="skeleton-row" aria-hidden="true" />
      <span className="skeleton-row short" aria-hidden="true" />
    </div>
  );
}

/** An error with a Reload button: works for a failed load and after a failed save. */
export function LoadError({ error, onRetry }: { error: string; onRetry(): void }) {
  return (
    <p className="error load-error" role="alert">
      <span>{error}</span>
      <button className="quiet" onClick={onRetry}>
        Reload
      </button>
    </p>
  );
}
