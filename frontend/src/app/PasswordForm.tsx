/**
 * Changing your own password: forced after the owner set it (new staff or a
 * reset), or by choice from the account sheet. Needs internet.
 */
import { useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { passwordProblem } from "../lib/staff";
import { explainError } from "./errors";
import { Sheet } from "./Sheet";
import { VoiceSettings } from "./VoiceSettings";
import { useSession } from "./session";
import { t, useLang } from '../lib/i18n';

export function PasswordForm({
  forced,
  onDone,
}: {
  forced: boolean;
  onDone?(): void;
}) {
  useLang();
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
      return setError(t("The two new passwords are not the same."));
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
        {forced ? t("Password the owner gave you") : t("Current password")}
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
        {t("New password")}
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
        {t("At least 8 characters. Not your phone number.")}
      </p>
      <label>
        {t("New password again")}
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
        {busy ? t("Saving…") : t("Save my password")}
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
        <h1>{t("Hello")} {user?.name}</h1>
        <p>
          {t("Choose your own password. Only you will know it, so the bills and changes you make are shown as yours.")}
        </p>
        <PasswordForm forced />
        <button className="quiet" onClick={() => void logout()}>
          {t("Log out")}
        </button>
      </div>
    </main>
  );
}

/** The account sheet: language, speaking aloud, and changing your own password. */
export function AccountSheet({ onClose }: { onClose(): void }) {
  const { user } = useSession();
  if (!user) return null;
  return createPortal(
    // Out of the top bar's text styles: the sheet belongs to the page.
    <Sheet title={`${user.name}: change my password`} onClose={onClose}>
      <VoiceSettings />
      <PasswordForm forced={false} onDone={onClose} />
      <p className="muted">{t("Needs internet. Saving logs you out on your other phones and tablets.")}</p>
    </Sheet>,
    document.body,
  );
}

/** The logged-in person's name in the top bar; tapping it opens the account sheet. */
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
      {open && <AccountSheet onClose={() => setOpen(false)} />}
    </>
  );
}
