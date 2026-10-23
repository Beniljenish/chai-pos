import { Component, type ReactNode } from 'react';
import { t } from '../lib/i18n';
import { reportError } from '../lib/reportError';

/** A screen that crashed shows a way out instead of a blank page, and the error is reported.
 * Bills already saved on the tablet are safe: they live in its own storage, not in the screen. */
export class CrashScreen extends Component<{ children: ReactNode }, { broken: boolean }> {
  state = { broken: false };

  static getDerivedStateFromError() {
    return { broken: true };
  }

  componentDidCatch(error: unknown) {
    reportError(error, 'screen');
  }

  render() {
    if (!this.state.broken) return this.props.children;
    return (
      <main className="centered">
        <div className="panel setup">
          <h1>{t('Something went wrong')}</h1>
          <p className="muted">{t('Saved bills are safe on this device. Reload to carry on.')}</p>
          <button className="primary" onClick={() => window.location.reload()}>
            {t('Reload')}
          </button>
        </div>
      </main>
    );
  }
}
