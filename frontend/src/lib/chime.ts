/** A short two-note chime made in the browser (no sound file to ship), for "an order arrived" and
 * "your order is ready". Browsers only let a page make sound after the person has tapped
 * something, so `unlockSound` is called from a tap (the "Sound on" switch, the notification
 * button); until then `chime` stays quiet instead of throwing. */

type AudioWindow = Window & { webkitAudioContext?: typeof AudioContext };

let ctx: AudioContext | null = null;

function audio(): AudioContext | null {
  try {
    const Ctor = window.AudioContext ?? (window as AudioWindow).webkitAudioContext;
    if (!Ctor) return null;
    ctx ??= new Ctor();
    return ctx;
  } catch {
    return null;
  }
}

/** Call from a tap. Returns whether sound can be made. */
export function unlockSound(): boolean {
  const c = audio();
  if (!c) return false;
  void c.resume();
  return true;
}

function note(c: AudioContext, freq: number, start: number, length: number) {
  const osc = c.createOscillator();
  const gain = c.createGain();
  osc.type = 'sine';
  osc.frequency.value = freq;
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.exponentialRampToValueAtTime(0.35, start + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + length);
  osc.connect(gain).connect(c.destination);
  osc.start(start);
  osc.stop(start + length + 0.05);
}

export function chime(): void {
  const c = audio();
  if (c && c.state === 'running') {
    const t = c.currentTime;
    note(c, 880, t, 0.35);
    note(c, 1320, t + 0.28, 0.5);
  }
  try {
    navigator.vibrate?.([200, 100, 200]);
  } catch {
    /* no vibration on this device */
  }
}
