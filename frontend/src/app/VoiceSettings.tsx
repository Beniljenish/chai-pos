/**
 * Language and "speak aloud" for this tablet or phone (README, "9.16"). Lives in the account sheet
 * so a cashier can reach it too. Saved on the device: each tablet at the counter chooses for itself.
 */
import { useState } from 'react';
import { loadSettings, phrase, saveSettings, type AnnounceSettings } from '../lib/announce';
import { t, useLang } from '../lib/i18n';
import { unlockSound } from '../lib/chime';
import { canSpeak, hasVoice, speak } from '../lib/voice';
import { LangSwitch } from './LangSwitch';

export function VoiceSettings() {
  const lang = useLang();
  const [s, setS] = useState<AnnounceSettings>(loadSettings);
  const can = canSpeak();
  const noTamil = can && lang === 'ta' && !hasVoice('ta');

  function change(patch: Partial<AnnounceSettings>) {
    const next = { ...s, ...patch };
    setS(next);
    saveSettings(next);
  }

  function test() {
    unlockSound();
    // Say the sample line even if the switch is still off: that is what the button is for.
    const l = lang === 'ta' && !hasVoice('ta') ? 'en' : lang;
    speak(phrase('ready', l, { token: 'JT-17' }), l, s.volume);
  }

  return (
    <section className="voice-settings" aria-label={t('Language and voice')}>
      <div className="voice-row">
        <strong>{t('Language')}</strong>
        <LangSwitch />
      </div>
      <label className="voice-row">
        <span>
          <strong>{t('Speak tokens and payments aloud')}</strong>
          <small className="muted">{t('Like a UPI soundbox. Saved on this device only.')}</small>
        </span>
        <input
          type="checkbox"
          checked={s.on}
          disabled={!can}
          onChange={(e) => {
            if (e.target.checked) unlockSound();
            change({ on: e.target.checked });
          }}
        />
      </label>
      {!can && <p className="muted">{t('This browser cannot speak aloud.')}</p>}
      {noTamil && <p className="muted">{t('This device has no Tamil voice, so it will speak English.')}</p>}
      {s.on && can && (
        <div className="voice-more">
          <label>
            <input type="checkbox" checked={s.ready} onChange={(e) => change({ ready: e.target.checked })} />
            {t('Token ready')}
          </label>
          <label>
            <input type="checkbox" checked={s.paid} onChange={(e) => change({ paid: e.target.checked })} />
            {t('Payment received')}
          </label>
          <label>
            <input type="checkbox" checked={s.order} onChange={(e) => change({ order: e.target.checked })} />
            {t('New online order')}
          </label>
          <label className="voice-volume">
            {t('Volume')}
            <input
              type="range"
              min={0.2}
              max={1}
              step={0.1}
              value={s.volume}
              onChange={(e) => change({ volume: Number(e.target.value) })}
            />
          </label>
          <button type="button" onClick={test}>
            {t('Test voice')}
          </button>
        </div>
      )}
    </section>
  );
}

