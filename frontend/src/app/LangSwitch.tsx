/** Tamil / English, one tap. Used on the customer pages, the log-in page and in Manage. */
import { LANGUAGES, setLang, t, useLang } from '../lib/i18n';

export function LangSwitch({ className = '' }: { className?: string }) {
  const lang = useLang();
  return (
    <div className={`lang-switch ${className}`} role="group" aria-label={t('Language')}>
      {LANGUAGES.map((l) => (
        <button
          key={l.id}
          type="button"
          aria-pressed={lang === l.id}
          lang={l.id}
          onClick={() => setLang(l.id)}
        >
          {l.label}
        </button>
      ))}
    </div>
  );
}
