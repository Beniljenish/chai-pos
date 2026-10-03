/**
 * Changing your own password: forced after the owner set it (new staff or a
 * reset), or by choice from the account sheet. Needs internet.
 */
import { useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { passwordProblem } from "../lib/staff";
import { explainError } from "./errors";
import { Sheet } from "./Sheet";
import { useSession } from "./session";

export function PasswordForm({
  forced,
  onDone,
}: {
  forced: boolean;
  onDone?(): void;
}) {
  const { user, changePassword } = useSession();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const problem = passwordProblem(next, user?.phone ?? "");
    if (problem) return setError(problem);
    if (next !== again)
      return setError("The two new passwords are not the same.");
    setBusy(true);
    setError(null);
    try {
      await changePassword(current, next);
      onDone?.();
    } catch (err) {
      setError(explainError(err));
      setBusy(false);
    }
  }

  return (
    <form className="password-form" onSubmit={submit}>
      <label>
        {forced ? "Password the owner gave you" : "Current password"}
        <input
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(e) => {
            setCurrent(e.target.value);
            setError(null);
          }}
          required
        />
      </label>
      <label>
        New password
        <input
          type="password"
          autoComplete="new-password"
          aria-describedby="new-password-rules"
          value={next}
          onChange={(e) => {
            setNext(e.target.value);
            setError(null);
          }}
          required
        />
      </label>
      <p id="new-password-rules" className="muted hint">
        At least 8 characters. Not your phone number.
      </p>
      <label>
        New password again
        <input
          type="password"
          autoComplete="new-password"
          value={again}
          onChange={(e) => {
            setAgain(e.target.value);
            setError(null);
          }}
          required
        />
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button className="primary" disabled={busy}>
        {busy ? "Saving…" : "Save my password"}
      </button>
    </form>
  );
}

/** Full screen after logging in with a password the owner set. */
export function SetPasswordScreen() {
  const { user, logout } = useSession();
  return (
    <main className="centered">
      <div className="panel login">
        <h1>Hello {user?.name}</h1>
        <p>
          Choose your own password. Only you will know it, so the bills and
          changes you make are shown as yours.
        </p>
        <PasswordForm forced />
        <button className="quiet" onClick={() => void logout()}>
          Log out
        </button>
      </div>
    </main>
  );
}

/** The logged-in person's name in the top bar; tapping it offers a password change. */
export function AccountButton() {
  const { user } = useSession();
  const [open, setOpen] = useState(false);
  if (!user) return null;
  return (
    <>
      <button
        className="account"
        aria-label={`${user.name}: change my password`}
        onClick={() => setOpen(true)}
      >
        {user.name}
      </button>
      {open &&
        // Out of the top bar's text styles: the sheet belongs to the page.
        createPortal(
          <Sheet
            title={`${user.name}: change my password`}
            onClose={() => setOpen(false)}
          >
            <PasswordForm forced={false} onDone={() => setOpen(false)} />
            <p className="muted">
              Needs internet. Saving logs you out on your other phones and
              tablets.
            </p>
          </Sheet>,
          document.body,
        )}
    </>
  );
}
