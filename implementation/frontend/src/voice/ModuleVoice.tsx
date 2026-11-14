import { useEffect, useRef, useState } from 'react';
import { AudioRecorder } from '../services/audioRecorder';
import { AudioPlayer } from '../services/audioPlayer';
import { VoiceController } from './controller';
import { resolveSpeechSelection } from './languages';
import {
  loadAudioPreferences, loadSpeechPreferences, shouldRequestVoice,
  subscribeAudioPreferences, subscribeSpeechPreferences,
  type AudioPreferences, type SpeechPreferences,
} from './preferences';

export interface ModuleVoiceProps {
  module: 'lesson' | 'interview' | 'redrive';
  sessionId: string;
  epoch: number;
  workspace: { id: string; token: string };
  messageId?: string;
  onTranscript: (text: string) => void;
}

type Phase = 'idle' | 'permission' | 'recording' | 'recognizing' | 'loading' | 'playing';
interface Runtime {
  recorder: AudioRecorder;
  player: AudioPlayer;
  controller: VoiceController;
  abort: AbortController | null;
  generation: number;
  audio: AudioPreferences;
  speech: SpeechPreferences;
}
const CLIENT_DEADLINE_MS = 65_000;
const MAX_VOICE_AUDIO_BASE64 = 12 * 1024 * 1024;

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function audioBytes(value: unknown): Uint8Array {
  if (typeof value !== 'string' || !value.length || value.length > MAX_VOICE_AUDIO_BASE64) {
    throw new Error('Invalid voice audio. Continue with text.');
  }
  return Uint8Array.from(atob(value), char => char.charCodeAt(0));
}
function encodeAudio(bytes: Uint8Array): string {
  // Avoid a giant spread or argument list for the bounded 1 MiB recording.
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 8192) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  }
  return btoa(binary);
}
function stop(runtime: Runtime): void {
  runtime.generation++;
  runtime.abort?.abort(); runtime.abort = null;
  runtime.controller.bargeInStop();
}
async function requestVoice(url: string, workspace: ModuleVoiceProps['workspace'],
  body: object, abort: AbortController): Promise<Record<string, unknown>> {
  const deadline = setTimeout(() => abort.abort(), CLIENT_DEADLINE_MS);
  try {
    const response = await fetch(url, {
      method: 'POST', signal: abort.signal, cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-Workspace-Id': workspace.id, 'X-Workspace-Token': workspace.token },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error('Voice unavailable or superseded. Continue with text.');
    const result: unknown = await response.json();
    if (!record(result)) throw new Error('Invalid voice response. Continue with text.');
    return result;
  } finally { clearTimeout(deadline); }
}

/** Explicit consent only. Changing source, epoch, or message destroys capture and replay. */
export function ModuleVoice(props: ModuleVoiceProps): JSX.Element {
  const key = JSON.stringify([props.module, props.sessionId, props.epoch, props.workspace.id, props.workspace.token, props.messageId]);
  return <SourceVoice key={key} {...props} />;
}

function SourceVoice({ module, sessionId, epoch, workspace, messageId, onTranscript }: ModuleVoiceProps): JSX.Element {
  const runtime = useRef<Runtime | null>(null);
  const transcript = useRef(onTranscript);
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [progress, setProgress] = useState(0);
  const [preferences, setPreferences] = useState(loadAudioPreferences);
  const endpoint = `/api/v1/module-voice/${module}/${encodeURIComponent(sessionId)}`;

  useEffect(() => { transcript.current = onTranscript; }, [onTranscript]);
  useEffect(() => {
    const player = new AudioPlayer();
    const current: Runtime = { recorder: new AudioRecorder(sessionId, epoch), player,
      controller: new VoiceController(player), abort: null, generation: 0,
      audio: loadAudioPreferences(), speech: loadSpeechPreferences() };
    runtime.current = current;
    const cancel = () => {
      stop(current); current.controller.clearReplay();
      void current.recorder.dispose(); setPhase('idle'); setProgress(0);
    };
    const unAudio = subscribeAudioPreferences(next => {
      current.audio = next; current.controller.setPreferences(next); setPreferences(next);
      if (next.textOnly || !shouldRequestVoice(next)) cancel();
    });
    const unSpeech = subscribeSpeechPreferences(next => {
      if (JSON.stringify(next) !== JSON.stringify(current.speech)) cancel();
      current.speech = next;
    });
    return () => {
      unAudio(); unSpeech(); stop(current); runtime.current = null;
      void current.recorder.dispose(); void current.controller.dispose();
    };
  }, [sessionId, epoch]);

  useEffect(() => {
    if (phase !== 'playing') return;
    const timer = setInterval(() => {
      const current = runtime.current;
      if (current) setProgress(current.player.playbackProgress);
    }, 100);
    return () => clearInterval(timer);
  }, [phase]);

  function fail(current: Runtime, generation: number, reason: unknown): void {
    if (runtime.current !== current || generation !== current.generation) return;
    setPhase('idle');
    setError(reason instanceof Error ? reason.message : 'Voice unavailable. Continue with text.');
  }

  async function finishRecording(): Promise<void> {
    const current = runtime.current;
    if (!current) return;
    const generation = ++current.generation;
    setPhase('recognizing'); setError('');
    try {
      const captured = await current.recorder.stopMicrophoneCapture();
      await current.recorder.dispose(); // Shared recorder clears its transient PCM buffers.
      if (runtime.current !== current || generation !== current.generation) return;
      if (captured.lowEnergyWarning) setNotice('Recording was quiet. Review your recognized draft.');
      const selection = resolveSpeechSelection(current.speech);
      const abort = new AbortController(); current.abort = abort;
      const result = await requestVoice(`${endpoint}/stt`, workspace,
        { epoch, audio_base64: encodeAudio(captured.wavBytes), language_mode: selection.language_mode }, abort);
      if (abort.signal.aborted || runtime.current !== current || generation !== current.generation) return;
      if (result.epoch !== epoch || result.requires_confirmation !== true
        || typeof result.normalized_transcript !== 'string' || result.normalized_transcript.length > 4000) {
        throw new Error('Recognition was superseded or invalid. Continue with text.');
      }
      transcript.current(result.normalized_transcript);
      setNotice('Recognized draft added. Review it before submitting.'); setPhase('idle');
    } catch (reason) { fail(current, generation, reason); }
  }

  async function startRecording(): Promise<void> {
    const current = runtime.current;
    if (!current || current.audio.textOnly) return;
    stop(current); const generation = current.generation;
    setError(''); setNotice(''); setPhase('permission');
    try {
      await current.recorder.startMicrophoneCapture({
        onSilenceTimeout: () => { void finishRecording(); },
        onBackpressureLimitReached: () => { void finishRecording(); },
        onDeviceLost: () => {
          stop(current); setPhase('idle'); setError('Microphone disconnected. Continue with text.');
        },
      });
      if (runtime.current === current && generation === current.generation) setPhase('recording');
    } catch (reason) { fail(current, generation, reason); }
  }

  async function listen(): Promise<void> {
    const current = runtime.current;
    if (!current || !messageId || !shouldRequestVoice(current.audio)) return;
    stop(current); const generation = current.generation;
    setError(''); setPhase('loading'); setProgress(0);
    const unlock = current.controller.unlockAudioFromGesture();
    try {
      if (!await unlock) throw new Error('Audio playback is blocked. Continue with text.');
      if (runtime.current !== current || generation !== current.generation) return;
      const abort = new AbortController(); current.abort = abort;
      // Shared controller replay is bounded and source-scoped; repeated listens are local.
      if (current.controller.hasReplay(messageId)) {
        const played = await current.controller.replay(abort.signal, messageId);
        if (runtime.current === current && generation === current.generation) {
          setPhase(played.started ? 'playing' : 'idle');
        }
        return;
      }
      const selection = resolveSpeechSelection(current.speech);
      const result = await requestVoice(`${endpoint}/tts`, workspace,
        { epoch, message_id: messageId, language: selection.language, voice: selection.voice }, abort);
      if (abort.signal.aborted || runtime.current !== current || generation !== current.generation) return;
      if (result.epoch !== epoch || result.content_type !== 'audio/wav') {
        throw new Error('Voice result superseded or invalid. Continue with text.');
      }
      const played = await current.controller.play({ wavBytes: audioBytes(result.audio_base64),
        sessionId, turnId: messageId, turnGeneration: epoch,
        onEnded: () => { if (runtime.current === current && generation === current.generation) { setProgress(1); setPhase('idle'); } },
      }, abort.signal, messageId, `${module}:${sessionId}:${epoch}:${messageId}`);
      if (runtime.current !== current || generation !== current.generation) return;
      if (!played.started) throw new Error('Audio playback is blocked. Continue with text.');
      setPhase('playing');
    } catch (reason) { fail(current, generation, reason); }
  }

  function cancel(): void {
    const current = runtime.current;
    if (current) { stop(current); void current.recorder.dispose(); }
    setPhase('idle'); setProgress(0);
  }
  const busy = phase !== 'idle';
  return <section className="module-voice" aria-label="Module voice controls">
    <p>Voice captures a draft; answers are never submitted automatically.</p>
    <div className="voice-actions">
      {phase === 'recording'
        ? <button type="button" onClick={() => { void finishRecording(); }}>Stop recording</button>
        : <button type="button" disabled={busy || preferences.textOnly} onClick={() => { void startRecording(); }}>Record answer</button>}
      <button type="button" disabled={busy || !messageId || !shouldRequestVoice(preferences)} onClick={() => { void listen(); }}>Listen to coach</button>
      {busy && <button type="button" onClick={cancel}>Stop voice</button>}
    </div>
    <p role="status" aria-live="polite">{phase === 'permission' ? 'Waiting for microphone permission…'
      : phase === 'recording' ? 'Recording. Stop when your draft is ready.'
        : phase === 'recognizing' ? 'Recognizing your draft…'
          : phase === 'loading' ? 'Loading coach voice…' : notice}</p>
    {phase === 'playing' && <progress aria-label="Coach audio playback" value={progress} max={1} />}
    {error && <p role="alert">{error}</p>}
  </section>;
}
