import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { AudioRecorder } from './services/audioRecorder';
import { studioRequest, type StudioSession } from './studioApi';
import { loadAudioPreferences, loadSpeechPreferences, subscribeAudioPreferences, subscribeSpeechPreferences, shouldRequestVoice, DEFAULT_SPEECH_PREFERENCES } from './voice/preferences';
import { resolveSpeechSelection } from './voice/languages';

export type StudioVoiceEvent = { sequence: number; type: string; payload?: { epoch?: number; text?: string; question?: string } };
export type StudioVoiceProps = {
  session: StudioSession;
  epoch: number;
  events: StudioVoiceEvent[];
  /** Update the parent's editable draft only. The parent must require review/confirmation. */
  onTranscript: (text: string) => void;
  disabled?: boolean;
  /** Availability gate, not permission or speech consent. */
  voiceEnabled?: boolean;
  /** True only after media playback starts, never while fetching/preparing speech. */
  onPlaybackStateChange?: (playing: boolean) => void;
};
type Phase = 'idle' | 'requesting-permission' | 'recording' | 'transcribing' | 'preparing-speech' | 'speaking' | 'error';
type SpeechResult = { epoch: number; normalized_transcript?: unknown; audio_base64?: unknown };
const IDLE = 'Idle. Talk through your explanation, or type it below.';
const MAX_CAPTURE_BYTES = 1_048_576;
const BASE64_CHUNK_SIZE = 8192;
const MAX_RECORDING_DURATION_MS = 25_000;
const MAX_REPLAY_ENTRIES = 12;
const MAX_REPLAY_BYTES = 8 * 1024 * 1024;
type CachedAudio = {readonly url: string; readonly bytes: number};

function encodeRecording(bytes: Uint8Array): string {
  if (!(bytes instanceof Uint8Array) || !bytes.length || bytes.length > MAX_CAPTURE_BYTES) throw new Error('Invalid recording');
  let value = '';
  for (let index = 0; index < bytes.length; index += BASE64_CHUNK_SIZE) {
    value += String.fromCharCode(...bytes.subarray(index, index + BASE64_CHUNK_SIZE));
  }
  return btoa(value);
}
function decodeCoachAudio(value: unknown): Blob {
  if (typeof value !== 'string' || !value.length || value.length > Math.ceil(MAX_REPLAY_BYTES / 3) * 4) throw new Error('Invalid or oversized coach audio');
  const bytes = Uint8Array.from(atob(value), character => character.charCodeAt(0));
  if (!bytes.length || bytes.length > MAX_REPLAY_BYTES) throw new Error('Empty or oversized coach audio');
  return new Blob([bytes], { type: 'audio/wav' });
}
function latestCoach(events: StudioVoiceEvent[], epoch: number): StudioVoiceEvent | null {
  return events.reduce<StudioVoiceEvent | null>((latest, event) => {
    const question = event.payload?.question;
    const eligible = event.type === 'coach.action'
      || (event.type === 'feedback.ready' && typeof question === 'string' && question.trim().length > 0);
    if (!eligible || event.payload?.epoch !== epoch || !Number.isSafeInteger(event.sequence) || event.sequence < 1
      || (latest && event.sequence <= latest.sequence)) return latest;
    return event;
  }, null);
}

export function StudioVoice({ session, epoch, events, onTranscript, disabled = false, voiceEnabled = true, onPlaybackStateChange }: StudioVoiceProps) {
  const [audioPreferences, setAudioPreferences] = useState(loadAudioPreferences);
  const [speechPreferences, setSpeechPreferences] = useState(loadSpeechPreferences);
  const audioPreferencesRef = useRef(audioPreferences);
  const speechPreferencesRef = useRef(speechPreferences);
  const playbackCallback = useRef(onPlaybackStateChange);
  const isPlaying = useRef(false);
  const [phase, setPhase] = useState<Phase>('idle');
  const [status, setStatus] = useState(IDLE);
  const [micConsent, setMicConsent] = useState(false);
  const [speechEnabled, setSpeechEnabled] = useState(false);
  const consentId = useId();
  const recorder = useRef<AudioRecorder | null>(null);
  const captureDeadline = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pending = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const mounted = useRef(false);
  const currentPhase = useRef<Phase>('idle');
  const audio = useRef<HTMLAudioElement | null>(null);
  const cache = useRef<Readonly<Record<string, CachedAudio>>>({});
  const activeCacheKey = useRef<string | null>(null);
  const failedReplayKey = useRef<string | null>(null);
  const speechConsent = useRef(false);
  const observedSequence = useRef(-1);
  const initializedSession = useRef<string | null>(null);
  const transcriptCallback = useRef(onTranscript);
  const sessionHistory = useRef(events);
  const queuedCoach = useRef<StudioVoiceEvent | null>(null);
  const latest = latestCoach(events, epoch);
  const available = !disabled && voiceEnabled && !audioPreferences.textOnly;
  const speechAvailable = available && shouldRequestVoice(audioPreferences);
  const active = phase !== 'idle' && phase !== 'error';
  const cacheKey = useCallback((event: StudioVoiceEvent) => JSON.stringify([session.id, epoch, event.sequence, speechPreferences.spokenLanguage, speechPreferences.voice]), [session.id, epoch, speechPreferences.spokenLanguage, speechPreferences.voice]);
  const isCurrent = useCallback((local: number) => mounted.current && local === generation.current, []);

  const show = useCallback((next: Phase, message: string) => {
    currentPhase.current = next;
    const playing = next === 'speaking';
    if (playing !== isPlaying.current) { isPlaying.current = playing; playbackCallback.current?.(playing); }
    setPhase(next);
    setStatus(message);
  }, []);
  const clearCaptureDeadline = useCallback(() => {
    if (captureDeadline.current !== null) clearTimeout(captureDeadline.current);
    captureDeadline.current = null;
  }, []);
  const detachActive = useCallback(() => {
    generation.current++;
    if (isPlaying.current) { isPlaying.current = false; playbackCallback.current?.(false); }
    activeCacheKey.current = null;
    clearCaptureDeadline();
    pending.current?.abort();
    pending.current = null;
    const old = recorder.current;
    recorder.current = null;
    if (audio.current?.hasAttribute('src')) {
      audio.current.pause();
      audio.current.removeAttribute('src');
    }
    queuedCoach.current = null;
    return old;
  }, [clearCaptureDeadline]);
  const dispose = useCallback(async function disposeRecorder(item: AudioRecorder, local: number): Promise<void> {
    try { await item.dispose(); }
    catch {
      if (!isCurrent(local)) return;
      if (recorder.current === item) recorder.current = null;
      const interrupted = detachActive();
      if (interrupted) void disposeRecorder(interrupted, generation.current);
      show('error', 'Error. Microphone cleanup failed. Close this tab to release it; text remains available.');
    }
  }, [detachActive, isCurrent, show]);
  const invalidate = useCallback(() => {
    const old = detachActive();
    if (old) void dispose(old, generation.current);
  }, [detachActive, dispose]);
  const evictAudio = useCallback((key: string) => {
    const entry = cache.current[key];
    if (!entry) return;
    URL.revokeObjectURL(entry.url);
    cache.current = Object.fromEntries(Object.entries(cache.current).filter(([existing]) => existing !== key));
  }, []);
  const clearAudioCache = useCallback(() => {
    Object.values(cache.current).forEach(entry => URL.revokeObjectURL(entry.url));
    cache.current = {};
    failedReplayKey.current = null;
  }, []);
  function cancel() {
    invalidate();
    show('idle', 'Idle. Voice stopped. Text remains available.');
  }

  useLayoutEffect(() => { transcriptCallback.current = onTranscript; }, [onTranscript]);
  useLayoutEffect(() => { playbackCallback.current = onPlaybackStateChange; }, [onPlaybackStateChange]);
  useLayoutEffect(() => subscribeAudioPreferences(next => {
    audioPreferencesRef.current = next;
    setAudioPreferences(next);
    if (audio.current) { audio.current.volume = next.volume; audio.current.muted = next.muted; audio.current.playbackRate = next.speed; }
    if (next.textOnly || (!shouldRequestVoice(next) && ['preparing-speech','speaking'].includes(currentPhase.current))) {
      invalidate(); show('idle','Idle. Voice disabled by your preferences. Text remains available.');
    }
  }), [invalidate, show]);
  useLayoutEffect(() => subscribeSpeechPreferences(next => {
    const prior = speechPreferencesRef.current;
    speechPreferencesRef.current = next;
    setSpeechPreferences(next);
    if (JSON.stringify(resolveSpeechSelection(prior)) !== JSON.stringify(resolveSpeechSelection(next))) {
      invalidate(); clearAudioCache(); show('idle','Idle. Speech preferences changed. Start voice again when ready.');
    }
  }), [invalidate, clearAudioCache, show]);
  useLayoutEffect(() => { sessionHistory.current = events; }, [events]);

  // Consent is scoped to a session capability, never inferred from a prop or persisted.
  useLayoutEffect(() => {
    setMicConsent(false);
    setSpeechEnabled(false);
    speechConsent.current = false;
  }, [session.id, session.token]);
  useLayoutEffect(() => {
    mounted.current = true;
    const capabilityKey = JSON.stringify([session.id, session.token]);
    if (initializedSession.current !== capabilityKey) {
      initializedSession.current = capabilityKey;
      observedSequence.current = sessionHistory.current.reduce((highest, event) => (
        Number.isSafeInteger(event.sequence) ? Math.max(highest, event.sequence) : highest
      ), -1);
    }
    show('idle', IDLE);
    return () => {
      mounted.current = false;
      invalidate();
      clearAudioCache();
    };
    // Initial session history is a baseline; epoch transitions retain the observed
    // sequence so unseen replies remain eligible after old audio is invalidated.
  }, [session.id, session.token, epoch, invalidate, clearAudioCache, show]);
  useLayoutEffect(() => {
    if (!available) {
      invalidate();
      show('idle', 'Idle. Voice is unavailable right now. Use text.');
    }
  }, [available, invalidate, show]);

  async function start() {
    if (!available || (currentPhase.current !== 'idle' && currentPhase.current !== 'error')) return;
    invalidate();
    setMicConsent(true);
    const local = generation.current;
    const item = new AudioRecorder(session.id, epoch);
    recorder.current = item;
    show('requesting-permission', 'Requesting microphone permission…');
    try {
      await item.startMicrophoneCapture({
        onDeviceLost: () => {
          if (!isCurrent(local)) return;
          invalidate();
          show('error', 'Error. Microphone disconnected. Your text remains available; try Talk again.');
        },
        onBackpressureLimitReached: () => {
          if (!isCurrent(local)) return;
          invalidate();
          show('error', 'Error. Recording limit reached. Try a shorter explanation; nothing was submitted.');
        },
      });
      if (!isCurrent(local) || recorder.current !== item) { await dispose(item, local); return; }
      show('recording', 'Recording. Stops after 25 seconds, or choose Stop and transcribe to review your explanation.');
      captureDeadline.current = setTimeout(() => {
        if (!isCurrent(local) || recorder.current !== item) return;
        captureDeadline.current = null;
        void transcribe();
      }, MAX_RECORDING_DURATION_MS);
    } catch {
      if (isCurrent(local)) {
        recorder.current = null;
        show('error', 'Error. Microphone unavailable or permission denied. Use text, or try Talk again.');
      }
      await dispose(item, local);
    }
  }

  async function transcribe() {
    const item = recorder.current;
    if (!available || !item || currentPhase.current !== 'recording') return;
    clearCaptureDeadline();
    const local = ++generation.current;
    show('transcribing', 'Transcribing with Gnani…');
    try {
      const captured = await item.stopMicrophoneCapture();
      if (!isCurrent(local) || recorder.current !== item) return;
      const controller = new AbortController();
      pending.current = controller;
      const result = await studioRequest<SpeechResult>(`/studio/sessions/${encodeURIComponent(session.id)}/speech/stt`, {
        method: 'POST', token: session.token, signal: controller.signal,
        body: { epoch, audio_base64: encodeRecording(captured.wavBytes), language_mode: resolveSpeechSelection(speechPreferencesRef.current).language_mode },
      });
      if (!isCurrent(local)) return;
      if (!result) throw new Error('Invalid speech response');
      if (result.epoch !== epoch) { show('error', 'Error. Stale transcript ignored. Try Talk again.'); return; }
      if (typeof result.normalized_transcript !== 'string' || !result.normalized_transcript.trim()) {
        show('error', 'Error. No usable transcript returned. Try Talk again, or type your explanation.');
        return;
      }
      transcriptCallback.current(result.normalized_transcript);
      show('idle', 'Idle. Review the transcript in your explanation below, then confirm. Nothing has been submitted.');
    } catch {
      if (isCurrent(local)) show('error', 'Error. Transcription unavailable. Your explanation is unchanged; use text or try Talk again.');
    } finally {
      await dispose(item, local);
      if (recorder.current === item) recorder.current = null;
      if (isCurrent(local)) pending.current = null;
    }
  }

  const playCached = useCallback(async (url: string, local: number, key: string) => {
    const player = audio.current;
    if (!isCurrent(local) || !player || !shouldRequestVoice(audioPreferencesRef.current)) return;
    activeCacheKey.current = key;
    player.volume = audioPreferencesRef.current.volume;
    player.muted = audioPreferencesRef.current.muted;
    player.playbackRate = audioPreferencesRef.current.speed;
    player.src = url;
    player.currentTime = 0;
    try {
      await player.play();
      if (isCurrent(local)) show('speaking', 'Speaking. Listen to the Gnani coach, or stop voice.');
    } catch (error) {
      if (!isCurrent(local)) return;
      if (!(error instanceof DOMException && error.name === 'NotAllowedError')) evictAudio(key);
      failedReplayKey.current = key;
      show('error', 'Error. Playback was blocked or unavailable. Choose Replay coach to listen; coach text remains available.');
    }
  }, [isCurrent, show, evictAudio]);

  const speak = useCallback(async (event: StudioVoiceEvent) => {
    if (!speechAvailable || !speechConsent.current) return;
    invalidate();
    const local = generation.current;
    show('preparing-speech', 'Preparing Gnani coach audio…');
    const key = cacheKey(event);
    try {
      let url = cache.current[key]?.url;
      if (!url) {
        const controller = new AbortController();
        pending.current = controller;
        const result = await studioRequest<SpeechResult>(`/studio/sessions/${encodeURIComponent(session.id)}/speech/tts`, {
          method: 'POST', token: session.token, signal: controller.signal,
          body: { epoch, event_sequence: event.sequence,
            ...(speechPreferencesRef.current.spokenLanguage !== DEFAULT_SPEECH_PREFERENCES.spokenLanguage || speechPreferencesRef.current.voice !== DEFAULT_SPEECH_PREFERENCES.voice
              ? {language:speechPreferencesRef.current.spokenLanguage,voice:speechPreferencesRef.current.voice} : {}) },

        });
        if (!isCurrent(local)) return;
        if (!result || result.epoch !== epoch) throw new Error('Stale coach audio');
        const blob = decodeCoachAudio(result.audio_base64);
        while (Object.keys(cache.current).length >= MAX_REPLAY_ENTRIES || Object.values(cache.current).reduce((sum,entry)=>sum+entry.bytes,0) + blob.size > MAX_REPLAY_BYTES) {
          evictAudio(Object.keys(cache.current)[0]);
        }
        url = URL.createObjectURL(blob);
        cache.current = { ...cache.current, [key]: {url,bytes:blob.size} };
      }
      await playCached(url, local, key);
    } catch {
      if (isCurrent(local)) show('error', 'Error. Gnani coach audio unavailable. Read the coach text, or try Play coach again.');
    } finally {
      if (isCurrent(local)) pending.current = null;
    }
  }, [speechAvailable, invalidate, show, cacheKey, session.id, session.token, epoch, isCurrent, playCached, evictAudio]);

  function enableCoachSpeech() {
    if (!speechAvailable || (currentPhase.current !== 'idle' && currentPhase.current !== 'error')) return;
    speechConsent.current = true;
    setSpeechEnabled(true);
    queuedCoach.current = null;
    if (latest) {
      observedSequence.current = Math.max(observedSequence.current, latest.sequence);
      void speak(latest);
    } else show('idle', 'Idle. Coach speech enabled. New coach replies will play with Gnani audio.');
  }

  useEffect(() => {
    if (latest && latest.sequence > observedSequence.current) {
      observedSequence.current = latest.sequence;
      if (speechConsent.current && speechAvailable) queuedCoach.current = latest;
    }
    const next = queuedCoach.current;
    if (!next || !speechConsent.current || !speechAvailable) return;
    if (['requesting-permission', 'recording', 'transcribing', 'preparing-speech'].includes(currentPhase.current)) return;
    queuedCoach.current = null;
    void speak(next);
    // Repeated snapshot identities cannot trigger replay: the observed sequence
    // guards fresh playback, while the stable lifecycle callbacks preserve context.
  }, [latest, phase, speechEnabled, speechAvailable, speak]);

  const micLabel = phase === 'recording' ? 'Stop and transcribe' : micConsent ? 'Talk' : 'Enable voice and talk';
  const coachLabel = !speechEnabled ? 'Enable coach speech' : latest && (cache.current[cacheKey(latest)] || failedReplayKey.current === cacheKey(latest)) ? 'Replay coach' : 'Play coach';
  return <section className="studio-voice" aria-label="Gnani voice">
    <p id={consentId}>Choosing Enable voice and talk or Enable coach speech gives consent to send audio or coach text to Gnani. Speech enables new coach replies to play automatically. Text remains available.</p>
    <div className="studio-actions" aria-label="Voice controls">
      <button type="button" className="primary" aria-describedby={consentId} aria-pressed={phase === 'recording'}
        disabled={!available || (active && phase !== 'recording')} onClick={() => void (phase === 'recording' ? transcribe() : start())}>
        <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/></svg>
        {micLabel}
      </button>
      {active ? <button type="button" onClick={cancel}>{phase === 'speaking' ? 'Stop voice' : 'Cancel voice'}</button>
        : <button type="button" aria-describedby={consentId} disabled={!speechAvailable || (speechEnabled && !latest)} onClick={enableCoachSpeech}>{coachLabel}</button>}
    </div>
    <p role="status" aria-live="polite" aria-atomic="true" data-voice-state={phase}>{status}</p>
    {/* eslint-disable-next-line jsx-a11y/media-has-caption -- Audio-only TTS duplicates the parent's visible exact coach text/question (WCAG 1.2.1 text alternative); no video or fake caption track. */}
    <audio ref={audio} hidden preload="none" onEnded={() => {
      if (currentPhase.current === 'speaking') show('idle', 'Idle. Coach audio finished. Replay is available without another Gnani request.');
    }} onError={() => {
      if (currentPhase.current === 'speaking' || currentPhase.current === 'preparing-speech') {
        const key = activeCacheKey.current;
        if (key) { evictAudio(key); failedReplayKey.current = key; }
        invalidate();
        show('error', 'Error. Coach audio playback unavailable. Read the coach text, or choose Replay coach.');
      }
    }} />
  </section>;
}
