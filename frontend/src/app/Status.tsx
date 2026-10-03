/**
 * The two states every screen that loads from the server can be in before it has
 * data: still loading, or the load failed. One look everywhere, and a failed load
 * can always be retried in place (README, "Phase 5.4").
 */
export function Loading({ what }: { what?: string }) {
  return (
    <p className="muted" role="status">
      Loading{what ? ` ${what}` : ''}…
    </p>
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
