import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { AudioRecorder, MicrophoneCaptureError } from '../../services/audioRecorder';
import { loadInputDeviceId, saveInputDeviceId, subscribeInputDeviceId } from '../../voice/inputDevices';

const CHECK_DURATION_MS = 2000;
type Phase = 'idle' | 'permission' | 'recording' | 'stopping';
type CheckStats = { durationSec: number; rms: number; peak: number; quiet: boolean; clipped: boolean };
type Attempt = { recorder: AudioRecorder; generation: number; inputId: string | null; timer: ReturnType<typeof setTimeout> | null };
const serverInputId = (): null => null;

function inputDevices(list: MediaDeviceInfo[]): MediaDeviceInfo[] {
  const seen = new Set<string>();
  return list.filter(device => {
    if (device.kind !== 'audioinput' || !device.deviceId || device.deviceId === 'default' || seen.has(device.deviceId)) return false;
    seen.add(device.deviceId);
    return true;
  });
}
function captureMessage(error: unknown): string {
  if (error instanceof MicrophoneCaptureError && error.code !== 'WORKLET_INIT_FAILED') return error.message;
  if (error instanceof Error && /empty|0 samples/i.test(error.message)) return 'No audio captured (empty recording). Try again, or continue with typed input.';
  return 'Microphone check could not complete. Check browser microphone access or choose System default. You can continue with typed input.';
}

/** Explicit, local-only diagnostics; no playback, transcription, uploads, or session access. */
export function MicrophoneCheck() {
  const selectedId = useSyncExternalStore(subscribeInputDeviceId, loadInputDeviceId, serverInputId);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [enumerationError, setEnumerationError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [stats, setStats] = useState<CheckStats | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const mounted = useRef(false);
  const generation = useRef(0);
  const enumerationGeneration = useRef(0);
  const active = useRef<Attempt | null>(null);
  const checkButton = useRef<HTMLButtonElement>(null);
  const restoreCheckFocus = useRef(false);

  const cancelAttempt = useCallback(async (attempt: Attempt, message: string, failed: boolean) => {
    if (active.current !== attempt) return;
    active.current = null;
    const fence = ++generation.current;
    if (attempt.timer !== null) clearTimeout(attempt.timer);
    attempt.timer = null;
    setPhase('stopping');
    await attempt.recorder.dispose();
    if (!mounted.current || generation.current !== fence) return;
    setPhase('idle');
    setStats(null);
    setError(failed ? message : null);
    setNotice(failed ? null : message);
  }, []);

  const refresh = useCallback(async () => {
    const fence = ++enumerationGeneration.current;
    const media = typeof navigator === 'undefined' ? undefined : navigator.mediaDevices;
    if (!media || typeof media.enumerateDevices !== 'function') {
      setEnumerationError('Microphone listing is not available in this browser. You can still use typed input.');
      return;
    }
    try {
      const list = await media.enumerateDevices();
      if (!mounted.current || fence !== enumerationGeneration.current) return;
      if (!Array.isArray(list)) throw new Error('Invalid device listing');
      const inputs = inputDevices(list);
      setDevices(inputs);
      setEnumerationError(null);
      const attempt = active.current;
      if (attempt?.inputId && !inputs.some(device => device.deviceId === attempt.inputId)) {
        void cancelAttempt(attempt, 'Selected microphone disconnected or is no longer available. Choose System default, or continue with typed input.', true);
      }
    } catch {
      if (mounted.current && fence === enumerationGeneration.current) setEnumerationError('Unable to list microphones. Try Refresh microphones; permission is only requested by Check microphone.');
    }
  }, [cancelAttempt]);

  const disposeActive = useCallback(() => {
    mounted.current = false;
    ++enumerationGeneration.current;
    ++generation.current;
    const attempt = active.current;
    active.current = null;
    if (attempt) {
      if (attempt.timer !== null) clearTimeout(attempt.timer);
      void attempt.recorder.dispose();
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const media = typeof navigator === 'undefined' ? undefined : navigator.mediaDevices;
    const changed = () => { void refresh(); };
    media?.addEventListener?.('devicechange', changed);
    return () => {
      disposeActive();
      media?.removeEventListener?.('devicechange', changed);
    };
  }, [refresh, disposeActive]);

  useEffect(() => {
    if (phase !== 'idle' || !restoreCheckFocus.current) return;
    restoreCheckFocus.current = false;
    if (mounted.current && document.activeElement === document.body) checkButton.current?.focus();
  }, [phase]);

  async function finish(attempt: Attempt): Promise<void> {
    if (active.current !== attempt) return;
    attempt.timer = null;
    setPhase('stopping');
    let next: CheckStats | null = null;
    let failure: string | null = null;
    try {
      const capture = await attempt.recorder.stopMicrophoneCapture();
      try {
        if (capture.durationSec <= 0 || capture.wavBytes.byteLength <= 44) throw new Error('Empty recording');
        next = { durationSec: capture.durationSec, rms: capture.rmsNormalized, peak: capture.peakNormalized, quiet: capture.lowEnergyWarning, clipped: capture.clippedSamples > 0 };
      } finally { capture.wavBytes.fill(0); /* Erase this owned transient payload; retain only scalar diagnostics. */ }
    } catch (problem) { failure = captureMessage(problem); }
    finally { await attempt.recorder.dispose(); }
    if (!mounted.current || active.current !== attempt || generation.current !== attempt.generation) return;
    active.current = null;
    setPhase('idle');
    setStats(next);
    setError(failure);
  }

  async function check(): Promise<void> {
    if (active.current || phase !== 'idle') return;
    const attempt: Attempt = { recorder: new AudioRecorder('local-microphone-check'), generation: ++generation.current, inputId: loadInputDeviceId(), timer: null };
    active.current = attempt;
    restoreCheckFocus.current = false;
    setStats(null); setNotice(null); setError(null); setPhase('permission');
    try {
      await attempt.recorder.startMicrophoneCapture({
        onDeviceLost: () => { void cancelAttempt(attempt, 'Microphone lost during the check. Choose System default, or continue with typed input.', true); },
        onBackpressureLimitReached: () => { void cancelAttempt(attempt, 'Microphone check reached the capture limit. Try again, or continue with typed input.', true); },
      });
      if (!mounted.current || active.current !== attempt || generation.current !== attempt.generation) {
        await attempt.recorder.dispose();
        return;
      }
      setPhase('recording');
      attempt.timer = setTimeout(() => { void finish(attempt); }, CHECK_DURATION_MS);
    } catch (problem) {
      if (active.current === attempt) await cancelAttempt(attempt, captureMessage(problem), true);
    }
  }

  function choose(id: string): void {
    if (active.current || phase !== 'idle') return;
    const saved = saveInputDeviceId(id || null);
    setError(saved ? null : 'Microphone input could not be saved on this device. Your previous selection is unchanged.');
    setNotice(saved ? 'Microphone input saved for the next capture. This does not grant microphone permission.' : null);
    setStats(null);
  }
  const busy = phase !== 'idle';
  const missing = selectedId !== null && !devices.some(device => device.deviceId === selectedId);
  const progress = phase === 'permission' ? 'Waiting for microphone permission and audio readiness…'
    : phase === 'recording' ? 'Checking microphone for two seconds…'
    : phase === 'stopping' ? 'Releasing microphone…' : notice;

  return <section aria-labelledby="microphone-check-title">
    <div className="setting-row"><div><h3 id="microphone-check-title">Microphone input</h3><p>Your selection applies to the next capture, including DSA, Studio, and lesson voice. You can always type instead.</p></div>
      <div className="setting-control"><label>Microphone input<select aria-label="Microphone input" value={selectedId ?? ''} disabled={busy} onChange={event => choose(event.target.value)}>
        <option value="">System default</option>
        {missing && <option value={selectedId}>Selected microphone — unavailable</option>}
        {devices.map((device, index) => <option key={device.deviceId} value={device.deviceId}>{device.label || `Microphone ${index + 1} — unlabelled`}</option>)}
      </select></label><button type="button" disabled={busy} onClick={() => { void refresh(); }}>Refresh microphones</button></div>
    </div>
    {!devices.length && !enumerationError && <p>No microphones listed. Refresh after connecting a microphone; no permission is requested by refreshing.</p>}
    <p className="settings-footnote">Local-only microphone check with no recording retention and no voice preview. Check microphone requests permission, captures two seconds after audio is ready, and immediately discards the recording. Only duration, RMS, and peak diagnostics remain on screen; nothing is uploaded.</p>
    <div className="button-row"><button ref={checkButton} type="button" disabled={busy} onClick={() => { void check(); }}>Check microphone</button>
      {busy && <button type="button" onClick={event => {
        const attempt = active.current;
        if (!attempt) return;
        restoreCheckFocus.current = document.activeElement === event.currentTarget;
        void cancelAttempt(attempt, 'Microphone check cancelled. No recording retained.', false);
      }}>Cancel microphone check</button>}
    </div>
    {enumerationError && <p role="alert" className="learning-notice">{enumerationError}</p>}
    {error && <p role="alert" className="learning-notice">{error}</p>}
    {(progress || stats) && <div role="status" className="settings-save-status">{stats ? <>Duration: {stats.durationSec.toFixed(2)} s · RMS: {stats.rms.toFixed(3)} · Peak: {stats.peak.toFixed(3)}</> : progress}</div>}
    {stats?.quiet && <p>Quiet input: move closer or check the microphone level before speaking.</p>}
    {stats?.clipped && <p>Clipped input: lower the microphone level or move farther away.</p>}
  </section>;
}
