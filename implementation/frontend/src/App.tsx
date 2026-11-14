import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { FALLBACK_BRANDING, applyDocumentBranding } from './config/branding';
import * as api from './services/apiClient';
import { AudioRecorder } from './services/audioRecorder';
import { AudioPlayer } from './services/audioPlayer';
import { PcmFrameWriter, StreamingPcmPlayer, consumeAudioEvents } from './services/speechStreaming';
import type { BrandingInfo, DemoPresetMetadata, ExerciseId, ExerciseMetadata, HealthResponse, HintLevel, RevisionRef, SpecVersion, VoicePlaybackAckRequest } from './types/api';
import { applyServerResult, confirmedInterpretation, coachingEntry, restoreWorkbench, sameRevision, canPublishTurn, reconcileVoiceRetry } from './state/sessionLifecycle';
import type { CoachingResponse, ResultResponse, TurnResponse } from './services/apiClient';
import { applyEditorBufferChange, createInitialWorkbenchState, resolveActiveWorkbenchView, type WorkbenchSessionState } from './state/useSessionStore';
import { LearningStepIndicator, CodeWorkspace, CoachingHintFeed, DiagnosticsDrawer, ExecutionComparisonCard, FreshCaseTransferCard, PredictionCaptureCard, ProblemConstraintPanel, TraceScrubberPanel } from './components/WorkbenchComponents';
import { ProblemLibrary } from './components/ProblemLibrary';
import { Icon } from './components/HorizonVisuals';
import { AccessibleTabs, ResizeHandle, SettingsDialog, WorkspaceHeader } from './components/WorkspaceChrome';
import { formatPrediction, parsePrediction } from './catalog/prediction';
import { VoiceController } from './voice/controller';
import { loadAudioPreferences, saveAudioPreferences, shouldPlayIntroduction, shouldRequestVoice, updateAudioPreferences, type AudioPreferences } from './voice/preferences';
import { DEFAULT_PRODUCT_STATE, draftKey, forgetTabSession, libraryUrl, loadProductState, problemUrl, readRoute, readTabSessions, rememberTabSession, saveProductState, type ProductRoute } from './state/productState';
import { getTeacherForSubject } from './config/teachers';
import './voice-first-workspace.css';
import { ActiveConversation, type ConversationEntry } from './components/ActiveConversation';
import { subscribeAudioPreferences, loadSpeechPreferences } from './voice/preferences';
import { resolveSpeechSelection } from './voice/languages';

const RESTORE_KEY = 'vcc-session';
function coachReplayKey(state: WorkbenchSessionState, level: HintLevel): string {
  const revision = state.revision;
  return JSON.stringify([state.sessionId, state.activeArtifact?.artifact_id, revision?.session_id, revision?.exercise_id, revision?.spec_version, revision?.code_version_id, revision?.code_hash, revision?.turn_generation, level]);
}

export function App(): React.ReactElement {
  const [branding, setBranding] = useState<BrandingInfo>(FALLBACK_BRANDING);
  const [health, setHealth] = useState<(HealthResponse & { execution_status?: 'DISABLED' | 'BLOCKED_EXTERNAL' | 'READY' }) | null>(null);
  const [exercises, setExercises] = useState<ExerciseMetadata[]>([]);
  const [presets, setPresets] = useState<DemoPresetMetadata[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [showTranscript, setShowTranscript] = useState(() => !location.pathname.startsWith('/practice/'));
  const voiceSubmitting = useRef(false);
  const voiceUploadRequest = useRef<AbortController | null>(null);
  const pendingVoiceFlush = useRef(false);
  const queuedVoiceSegments = useRef<Uint8Array[]>([]);
  const lastSpeechAt = useRef(0);
  const interruptedReply = useRef(false);
  const openingKey = useRef('');
  const retainedAudio = useRef<Uint8Array | null>(null);
  const [sttTransport, setSttTransport] = useState<'REST' | 'WS'>('REST');
  const [ttsTransport, setTtsTransport] = useState<'STREAM' | 'WAV'>('WAV');
  const [audioPreferences, setAudioPreferences] = useState(() => {
    const saved = loadAudioPreferences();
    try {
      if (!localStorage.getItem('viva.audio-preferences.v1') && loadProductState().inputChoice !== 'text') return updateAudioPreferences(saved, { introductions: true, autoSpeak: true });
    } catch { return saved; }
    return saved;
  });
  const audioPreferencesRef = useRef(audioPreferences);
  const [voiceMessage, setVoiceMessage] = useState('Audio is optional. Your editable caption and coach text are always available.');
  const [hasVoiceReplay, setHasVoiceReplay] = useState(false);
  const [coachReplayKeys, setCoachReplayKeys] = useState<readonly string[]>([]);
  const voiceReplayRevision = useRef<RevisionRef | null>(null);
  const orientationCache = useRef<{ key: string; audio: ArrayBuffer; playbackId: string | null } | null>(null);
  const playbackPurpose = useRef<'coach' | 'orientation' | 'replay' | null>(null);
  const [autoVoiceRequest, setAutoVoiceRequest] = useState<RevisionRef | null>(null);
  const [rms, setRms] = useState(0);
  const [micMessage, setMicMessage] = useState('Microphone setup is optional; typed input is always available.');
  const [workbench, setWorkbench] = useState(createInitialWorkbenchState);
  const [conversation, setConversation] = useState<ConversationEntry[]>([]);
  const [conversationSpeaker, setConversationSpeaker] = useState<'mentor' | 'student'>('mentor');
  const [mentorText, setMentorText] = useState('');
  const [audioProgress, setAudioProgress] = useState(1);
  const [product, setProduct] = useState(loadProductState);
  useEffect(() => subscribeAudioPreferences(preferences => setAudioPreferences(previous => JSON.stringify(previous) === JSON.stringify(preferences) ? previous : preferences)), []);
  useEffect(() => {
    const timer = window.setInterval(() => {
      setSpeaking(player.current.isPlaying);
      setAudioProgress(player.current.playbackProgress);
    }, 80);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!workbench.sessionId) { setConversation([]); setMentorText(''); return; }
    try {
      const raw: unknown = JSON.parse(sessionStorage.getItem(`viva.conversation.${workbench.sessionId}`) ?? '[]');
      const entries = Array.isArray(raw) ? raw.filter((entry): entry is ConversationEntry => typeof entry === 'object' && entry !== null && typeof entry.id === 'string' && typeof entry.text === 'string' && entry.text.length <= 8000 && ['mentor', 'student'].includes(entry.speaker)).slice(-60) : [];
      setConversation(entries);
      const last = entries[entries.length - 1];
      if (last) { setConversationSpeaker(last.speaker); if (last.speaker === 'mentor') setMentorText(last.text); }
    } catch { setStorageWarning('Conversation history could not be restored on this device.'); }
  }, [workbench.sessionId]);
  function appendConversation(entry: ConversationEntry): void {
    setConversation(previous => {
      const next = [...previous.filter(item => item.id !== entry.id), { ...entry, text: entry.text.slice(0, 8000) }].slice(-60);
      try { if (latest.current.sessionId) sessionStorage.setItem(`viva.conversation.${latest.current.sessionId}`, JSON.stringify(next)); }
      catch { setStorageWarning('Conversation history could not be saved on this device.'); }
      return next;
    });
    setConversationSpeaker(entry.speaker);
    if (entry.speaker === 'mentor') setMentorText(entry.text);
  }
  const productRef = useRef(product);
  const [route, setRoute] = useState(readRoute);
  const [settingsOpen, setSettingsOpen] = useState(() => {
    return typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('settings') === '1';
  });
  const closeSettings = () => {
    setSettingsOpen(false);
    if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('settings') === '1') {
      const url = new URL(window.location.href);
      url.searchParams.delete('settings');
      window.history.replaceState(null, '', url.pathname + (url.search ? url.search : ''));
    }
  };
  useEffect(() => {
    const handleSettingsQuery = () => {
      const search = new URLSearchParams(window.location.search);
      if (search.get('settings') === '1') {
        setSettingsOpen(true);
      }
    };
    const handleCustom = () => setSettingsOpen(true);
    window.addEventListener('viva:open-settings', handleCustom);
    window.addEventListener('popstate', handleSettingsQuery);
    return () => {
      window.removeEventListener('viva:open-settings', handleCustom);
      window.removeEventListener('popstate', handleSettingsQuery);
    };
  }, []);
  const [mobilePane, setMobilePane] = useState('Code');
  const [resultPane, setResultPane] = useState('Evidence');
  const [storageWarning, setStorageWarning] = useState<string | null>(null);
  const pageFocus = useRef<HTMLElement | null>(null);
  useLayoutEffect(() => { productRef.current = product; }, [product]);
  useEffect(() => { setStorageWarning(saveProductState(product)); }, [product]);
  useEffect(() => {
    const media = window.matchMedia?.('(prefers-color-scheme: dark)');
    const apply = () => { document.documentElement.dataset.theme = product.theme === 'system' ? (media?.matches ? 'dark' : 'light') : product.theme; };
    apply(); media?.addEventListener('change', apply);
    return () => media?.removeEventListener('change', apply);
  }, [product.theme]);
  const latest = useRef(workbench);
  useLayoutEffect(() => { latest.current = workbench; }, [workbench]);
  const saveChain = useRef<Promise<void>>(Promise.resolve());
  const recorder = useRef<AudioRecorder | null>(null);
  const player = useRef(new AudioPlayer());
  const voice = useRef(new VoiceController(player.current));
  useEffect(() => {
    audioPreferencesRef.current = audioPreferences;
    voice.current.setPreferences(audioPreferences); streamedPlayer.current?.setPreferences(audioPreferences);
    if (!saveAudioPreferences(audioPreferences)) setVoiceMessage('Audio preferences could not be saved on this device.');
    if (!shouldRequestVoice(audioPreferences)) effectActions.current.stopAudioPlayback();
  }, [audioPreferences]);
  const generation = useRef(0);
  const speechRequest = useRef<AbortController | null>(null);
  const speechRequestPurpose = useRef<'STT' | 'TTS' | null>(null);
  const captureCancellation = useRef(0);
  const liveSocket = useRef<WebSocket | null>(null);
  const frameWriter = useRef<PcmFrameWriter | null>(null);
  const socketResult = useRef<Promise<TurnResponse> | null>(null);
  const pendingTextMutation = useRef<{ sessionId: string; promise: Promise<TurnResponse> } | null>(null);
  const streamedPlayer = useRef<StreamingPcmPlayer | null>(null);
  const [predictedValue, setPredictedValue] = useState('');
  const [predictionReason, setPredictionReason] = useState('');
  const effectActions = useRef({ stopAudioPlayback, openLibrary, openProblem, stashDraft, playCoach, perform, startSession, playOrientation });
  useLayoutEffect(() => { effectActions.current = { stopAudioPlayback, openLibrary, openProblem, stashDraft, playCoach, perform, startSession, playOrientation }; });

  const operation = useRef(0);
  const errorFocus = useRef<HTMLDivElement | null>(null);
  useEffect(() => { if (error) errorFocus.current?.focus(); }, [error]);
  function fail(err: unknown): void { setError(err instanceof Error ? err.message : String(err)); }
  function stashDraft(s = latest.current): void {
    if ((!route.problemId && !s.sessionId) || (!s.sessionId && !s.editorDirty && !s.editableTranscript)) return;
    const key = draftKey(s.exerciseId, s.specVersion);
    const draft = { sourceCode: s.sourceCode, transcript: s.editableTranscript, updatedAt: Date.now(), status: s.editorDirty || !s.sessionId ? 'Draft' as const : 'In progress' as const };
    setProduct(prev => ({ ...prev, drafts: { ...prev.drafts, [key]: draft } }));
    const next = { ...productRef.current, drafts: { ...productRef.current.drafts, [key]: draft } };
    productRef.current = next; setStorageWarning(saveProductState(next));
  }
  function navigate(next: ProductRoute, replace = false): void {
    const url = next.problemId ? problemUrl(next.problemId, next.specVersion ?? '') : libraryUrl(next);
    history[replace ? 'replaceState' : 'pushState'](null, '', url); setRoute(next);
    window.dispatchEvent(new CustomEvent('viva:route-change'));
  }
  function initializeProblem(exercise: ExerciseMetadata, spec: string): WorkbenchSessionState {
    const draft = productRef.current.drafts[draftKey(exercise.exercise_id, spec)];
    return { ...createInitialWorkbenchState(), exerciseId: exercise.exercise_id as ExerciseId, specVersion: spec as SpecVersion,
      sourceCode: draft?.sourceCode ?? exercise.starter_code, persistedSourceCode: exercise.starter_code,
      editorDirty: !!draft && draft.sourceCode !== exercise.starter_code, editableTranscript: draft?.transcript ?? '',
      languageMode: productRef.current.language, specAcknowledged: spec !== 'v2_negatives_allowed', activeView: spec === 'v2_negatives_allowed' ? 'DOMAIN_SHIFT_ACK_GATE' : 'EXERCISE_BRIEF_SPEC' };
  }
  async function openProblem(problem: string, spec: string, push = true): Promise<void> {
    // Opening a problem must not override saved mute, autoplay, or text-only preferences.
    void voice.current.unlockAudioFromGesture();
    openingKey.current = ''; setShowTranscript(false);
    stashDraft(); const stopped = interruptLocal('Problem or specification changed');
    const epoch = generation.current;
    const exercise = exercises.find(item => item.exercise_id === problem);
    if (push) navigate({ ...route, problemId: problem, specVersion: spec });
    setError(null); setMobilePane('Code'); setResultPane('Evidence'); setPredictedValue(''); setPredictionReason('');
    setHasVoiceReplay(false); orientationCache.current = null; voiceReplayRevision.current = null;
    if (!exercise || !exercise.spec_versions.some(item => item.spec_version === spec)) { fail(new Error('This problem or specification is not in the current library.')); return; }
    setWorkbench(initializeProblem(exercise, spec));
    await stopped;
    const saved = readTabSessions()[draftKey(problem, spec)];
    if (saved) {
      api.registerSessionToken(saved.id, saved.token);
      try { const snapshot = await api.restoreSession(saved.id); if (generation.current === epoch) applySnapshot(snapshot, saved.token, true); }
      catch (err) { if (generation.current === epoch) fail(err); }
    }
    pageFocus.current?.focus();
  }
  function openLibrary(next: ProductRoute = { ...route, problemId: null, specVersion: null }, push = true): void {
    stashDraft(); void interruptLocal('Opened problem library').catch(fail);
    setWorkbench(prev => ({ ...prev, sessionId: null, sessionToken: null, activeTurnId: null, proposedClaim: null }));
    if (push) navigate(next); else setRoute(next);
    setError(null);
  }
  useEffect(() => {
    const pop = () => { const next = readRoute(); setRoute(next); if (next.problemId) void effectActions.current.openProblem(next.problemId, next.specVersion ?? exercises.find(e => e.exercise_id === next.problemId)?.default_spec_version ?? '', false).catch(fail); else effectActions.current.openLibrary(next, false); };
    window.addEventListener('popstate', pop); return () => window.removeEventListener('popstate', pop);
  }, [exercises, route]);
  useEffect(() => {
    if (!route.problemId || workbench.exerciseId !== route.problemId) return;
    effectActions.current.stashDraft();
  }, [workbench.sourceCode, workbench.editableTranscript, workbench.editorDirty, workbench.sessionId, workbench.exerciseId, route.problemId]);
  async function perform(action: () => Promise<void>): Promise<void> {
    const id = ++operation.current;
    setBusy(true); setError(null);
    try { await action(); } catch (err) {
      if (id !== operation.current || (err instanceof DOMException && err.name === 'AbortError')) return;
      fail(err);
      setWorkbench(prev => prev.learningState === 'VERIFYING' ? { ...prev, learningState: 'AWAITING_PREDICTION', activeView: 'QUEUE_DEGRADATION_RECOVERY' } : prev);
    } finally { if (id === operation.current) setBusy(false); }
  }
  function isCurrent(epoch: number, s: WorkbenchSessionState): boolean {
    return generation.current === epoch && latest.current.sessionId === s.sessionId && !latest.current.editorDirty && sameRevision(latest.current.revision, s.revision);
  }
  function acknowledgeInterruption(s: WorkbenchSessionState, ack: VoicePlaybackAckRequest): void {
    if (!s.sessionId || !s.revision || !ack.playback_id) return;
    const epoch = generation.current;
    void api.sendPlaybackAck(s.sessionId, { playback_id: ack.playback_id, revision: s.revision, playback_status: 'INTERRUPTED', played_duration_ms: ack.played_duration_ms ?? 0 }).catch(err => { if (isCurrent(epoch, s)) fail(err); });
  }
  function stopAudioPlayback(): void {
    setSpeaking(false);
    if (speechRequestPurpose.current === 'TTS') { speechRequest.current?.abort(); speechRequest.current = null; speechRequestPurpose.current = null; }
    void streamedPlayer.current?.stop(); streamedPlayer.current = null;
    const stopped = voice.current.bargeInStop(); const s = latest.current;
    if (playbackPurpose.current === 'coach' && stopped.ack) acknowledgeInterruption(s, stopped.ack);
  }
  function stopSpeechCapture(): void {
    captureCancellation.current++;
    if (speechRequestPurpose.current === 'STT') { speechRequest.current?.abort(); speechRequest.current = null; }
    liveSocket.current?.close(); liveSocket.current = null; frameWriter.current = null; socketResult.current = null;
    const capture = recorder.current; recorder.current = null; void capture?.dispose(); setRecording(false); setRms(0);
  }
  function interruptLocal(reason: string, resetBusy = true, signalServer = true): Promise<void> {
    retainedAudio.current = null; interruptedReply.current = false; voiceSubmitting.current = false; voiceUploadRequest.current = null;
    pendingVoiceFlush.current = false; queuedVoiceSegments.current = [];
    generation.current++;
    if (resetBusy) { operation.current++; setBusy(false); }
    setAutoVoiceRequest(null);
    speechRequest.current?.abort(); speechRequest.current = null;
    liveSocket.current?.close(); liveSocket.current = null; frameWriter.current = null; socketResult.current = null;
    void streamedPlayer.current?.stop(); streamedPlayer.current = null;
    const stopped = voice.current.bargeInStop();
    const s = latest.current;
    if (playbackPurpose.current === 'coach' && stopped.ack) acknowledgeInterruption(s, stopped.ack);
    voice.current.clearReplay(); setCoachReplayKeys([]); setHasVoiceReplay(false);
    voiceReplayRevision.current = null; orientationCache.current = null; playbackPurpose.current = null;
    const capture = recorder.current; recorder.current = null;
    void capture?.dispose(); setRecording(false); setRms(0);
    return signalServer && s.sessionId ? api.cancelSessionWork(s.sessionId, { scope: 'INTERRUPT', turn_id: s.activeTurnId, reason }).then(() => undefined) : Promise.resolve();
  }
  function changeCode(code: string): void {
    if (code === latest.current.sourceCode) return;
    if (!latest.current.editorDirty) void interruptLocal('Code buffer edited').catch(fail);
    else generation.current++;
    setWorkbench(prev => ({ ...applyEditorBufferChange(prev, code), proposedClaim: null, activeTurnId: null }));
  }
  function requireReady(): WorkbenchSessionState & { sessionId: string; revision: RevisionRef } {
    const s = latest.current;
    if (!s.sessionId || !s.revision) throw new Error('Start a session first.');
    if (s.editorDirty || s.saveInFlight) throw new Error('Save your current code before this action.');
    return s as WorkbenchSessionState & { sessionId: string; revision: RevisionRef };
  }
  function applySnapshot(snapshot: api.SessionSnapshot, token: string, preserveDraft = false): void {
    const restored = restoreWorkbench(snapshot, token);
    const draft = preserveDraft ? productRef.current.drafts[draftKey(restored.exerciseId, restored.specVersion)] : undefined;
    const next = draft && (draft.sourceCode !== restored.sourceCode || draft.transcript !== restored.editableTranscript) ? { ...applyEditorBufferChange(restored, draft.sourceCode), editableTranscript: draft.transcript, proposedClaim: null, activeTurnId: null } : restored;
    setWorkbench(next);
    if (next.proposedClaim?.claim_type === 'OUTPUT_PREDICTION_AND_REASON') {
      setPredictedValue(formatPrediction(next.proposedClaim.predicted_output)); setPredictionReason(next.proposedClaim.reason_summary ?? '');
    } else { setPredictedValue(''); setPredictionReason(''); }
  }
  useEffect(() => {
    let alive = true;
    const epoch = generation.current;
    const restoreAllowed = !latest.current.editorDirty && !latest.current.saveInFlight;
    setLoading(true);
    void (async () => {
      try {
        const [h, b, e, p] = await Promise.all([api.apiClient.getHealth(), api.apiClient.getBranding(), api.apiClient.getExercises(), api.apiClient.getDemoPresets()]);
        if (!alive) return;
        setHealth(h); setBranding(b); applyDocumentBranding(b); setExercises(e); setPresets(p);
        const initialRoute = readRoute();
        const selected = initialRoute.problemId ? e.find(item => item.exercise_id === initialRoute.problemId) : e[0];
        const spec = initialRoute.specVersion ?? selected?.default_spec_version;
        if (selected && spec) setWorkbench(prev => prev.sessionId || prev.editorDirty ? prev : initializeProblem(selected, spec));
        if (initialRoute.problemId && (!selected || !selected.spec_versions.some(s => s.spec_version === spec))) throw new Error('This problem or specification is not in the current library. Open the problem library to choose another.');
        const legacy = location.pathname === '/' ? sessionStorage.getItem(RESTORE_KEY) : null;
        const scoped = initialRoute.problemId && spec ? readTabSessions()[draftKey(initialRoute.problemId, spec)] : null;
        const saved = scoped ?? (legacy ? JSON.parse(legacy) as { id: string; token: string } : null);
        if (saved && restoreAllowed && generation.current === epoch && !latest.current.saveInFlight) {
          api.registerSessionToken(saved.id, saved.token);
          const snapshot = await api.restoreSession(saved.id);
          if (alive && generation.current === epoch && !latest.current.saveInFlight) {
            applySnapshot(snapshot, saved.token, true);
            rememberTabSession(snapshot.revision.exercise_id, snapshot.revision.spec_version, saved);
            if (legacy) navigate({ ...initialRoute, problemId: snapshot.revision.exercise_id, specVersion: snapshot.revision.spec_version }, true);
          }
        }
        if (alive) setError(null);
      } catch (err) { if (alive) fail(err); } finally { if (alive) setLoading(false); }
    })();
    return () => { alive = false; };
  }, [retry]);
  useEffect(() => {
    const activePlayer = new AudioPlayer(); const activeVoice = new VoiceController(activePlayer);
    player.current = activePlayer; voice.current = activeVoice; activeVoice.setPreferences(audioPreferencesRef.current);
    const generationRef = generation; const cancellationRef = captureCancellation;
    return () => { generationRef.current++; cancellationRef.current++; speechRequest.current?.abort(); liveSocket.current?.close(); void streamedPlayer.current?.stop(); void recorder.current?.dispose(); void activeVoice.dispose(); };
  }, []);

  async function startSession(exerciseId = latest.current.exerciseId, specVersion = latest.current.specVersion): Promise<void> {
    const settings = latest.current;
    const interrupted = interruptLocal('New practice session', false);
    setWorkbench(prev => ({ ...prev, activeArtifact: null, activeVerificationReport: null, activeTrace: null, activeChallenge: null, proposedClaim: null, activeTurnId: null, priorFailureArtifactId: null, coachingHistory: [] }));
    const epoch = generation.current;
    await interrupted;
    const speechSelection = resolveSpeechSelection(loadSpeechPreferences());
    const res = await api.createSession({ exercise_id: exerciseId, spec_version: specVersion, language_mode: speechSelection.language_mode, interaction_mode: latest.current.interactionMode, voice: speechSelection.voice, spoken_language: speechSelection.spoken_language });
    if (epoch !== generation.current) return;
    api.registerSessionToken(res.session_id, res.session_token);
    sessionStorage.setItem(RESTORE_KEY, JSON.stringify({ id: res.session_id, token: res.session_token }));
    rememberTabSession(exerciseId, specVersion, { id: res.session_id, token: res.session_token });
    const sourceCode = settings.exerciseId === exerciseId && settings.specVersion === specVersion ? settings.sourceCode : res.starter_code;
    const next = { ...createInitialWorkbenchState(), exerciseId, specVersion, sessionId: res.session_id, sessionToken: res.session_token, revision: res.revision,
      sourceCode, persistedSourceCode: res.starter_code, editorDirty: sourceCode !== res.starter_code, editableTranscript: settings.editableTranscript, sessionState: res.state, learningState: res.learning_state,
      specAcknowledged: res.spec_acknowledged, languageMode: speechSelection.language_mode, interactionMode: settings.interactionMode, turnGeneration: res.revision.turn_generation };
    const ready = { ...next, activeView: resolveActiveWorkbenchView(next) };
    latest.current = ready;
    setWorkbench(ready);
    setPredictedValue(''); setPredictionReason('');
    if (shouldPlayIntroduction(audioPreferencesRef.current)) await playOrientation('introduction', ready);
  }
  function saveCode(): Promise<void> {
    const captured = latest.current;
    if (!captured.sessionId || !captured.revision) return Promise.reject(new Error('Start a session before saving.'));
    const sessionId = captured.sessionId;
    setWorkbench(prev => ({ ...prev, saveInFlight: true }));
    saveChain.current = saveChain.current.catch(() => undefined).then(async () => {
      const current = latest.current;
      if (current.sessionId !== sessionId || current.specVersion !== captured.specVersion || current.exerciseId !== captured.exerciseId || !current.revision) return;
      const res = await api.updateSessionCode(sessionId, { code: captured.sourceCode, client_edit_sequence: captured.clientEditSequence, expected_code_version_id: current.revision.code_version_id });
      setWorkbench(prev => prev.sessionId !== sessionId || prev.specVersion !== captured.specVersion || prev.exerciseId !== captured.exerciseId ? prev : { ...prev, revision: res.revision, persistedSourceCode: captured.sourceCode,
        editorDirty: prev.sourceCode !== captured.sourceCode, saveInFlight: false, astSymbols: res.ast_symbols ?? [], syntaxError: res.syntax_error ?? null,
        turnGeneration: res.revision.turn_generation, captureAttemptId: 0, rawTranscript: '', editableTranscript: '', activeChallenge: null, proposedClaim: null, activeTurnId: null, activeArtifact: null, activeVerificationReport: null, activeTrace: null,
        coachingHistory: [], selectedTraceStepIndex: 0, diagnosticHidden: false, learningState: prev.priorFailureArtifactId ? 'REPAIR_REQUIRED' : 'EXPLAINING', activeView: prev.priorFailureArtifactId ? 'SOCRATIC_HINT_PROGRESSION' : 'EXPLAIN_APPROACH_TURN' });
    }).catch(err => { if (latest.current.sessionId !== sessionId || latest.current.specVersion !== captured.specVersion) return; setWorkbench(prev => ({ ...prev, saveInFlight: false })); fail(err); throw err; });
    return saveChain.current;
  }
  async function submitCode(): Promise<void> {
    if (latest.current.editorDirty) { await saveCode(); await new Promise<void>(resolve => requestAnimationFrame(() => resolve())); }
    if (latest.current.syntaxError) throw new Error(latest.current.syntaxError);
    setResultPane('Evidence');
    await verifyRepair();
  }
  async function issueChallenge(purpose: 'DIAGNOSTIC' | 'TRANSFER'): Promise<void> {
    const s = requireReady();
    const stopped = interruptLocal('New challenge', false, !!recorder.current?.isRecording || !!liveSocket.current);
    const epoch = generation.current;
    await stopped;
    const challenge = await api.createChallenge(s.sessionId, { purpose, revision: s.revision });
    if (!isCurrent(epoch, s)) return;
    setWorkbench(prev => ({ ...prev, revision: challenge.revision, turnGeneration: challenge.revision.turn_generation,
      activeChallenge: challenge, activeArtifact: null, activeVerificationReport: null, activeTrace: null, proposedClaim: null, activeTurnId: null, captureAttemptId: 0, rawTranscript: '', editableTranscript: '', diagnosticHidden: challenge.reveal_state !== 'REVEALED', coachingHistory: [],
      learningState: purpose === 'TRANSFER' ? 'FRESH_CASE_CHECK' : 'AWAITING_PREDICTION', activeView: purpose === 'TRANSFER' ? 'FRESH_TRANSFER_CHALLENGE' : 'PREDICT_CHALLENGE_OUTPUT' }));
    setPredictedValue(''); setPredictionReason('');
  }
  function applyTurn(res: TurnResponse, transcript: string): void {
    if (res.turn_generation !== undefined && res.turn_generation !== res.revision.turn_generation) throw new Error('Turn generation disagrees with its revision. Record or propose again.');
    if (!canPublishTurn(latest.current.revision, res.revision, !!latest.current.activeChallenge)) return;
    setProduct(prev => ({ ...prev, coachCollapsed: false })); setMobilePane('Coach');
    const next = { ...latest.current, activeTurnId: res.turn_id, revision: res.revision, proposedClaim: res.proposed_claim,
      turnGeneration: res.revision.turn_generation, captureAttemptId: res.capture_attempt_id,
      rawTranscript: transcript, editableTranscript: transcript, activeView: 'TRANSCRIPT_CLAIM_CONFIRMATION' as const };
    latest.current = next; setWorkbench(next);
    appendConversation({ id: `student-${res.turn_id}-${res.capture_attempt_id}`, speaker: 'student', text: transcript });
    if (res.proposed_claim.claim_type === 'OUTPUT_PREDICTION_AND_REASON') {
      setPredictedValue(formatPrediction(res.proposed_claim.predicted_output)); setPredictionReason(res.proposed_claim.reason_summary ?? '');
    }
  }
  async function sendTrackedText(sessionId: string, req: Parameters<typeof api.submitTextTurn>[1]): Promise<TurnResponse> {
    const promise = api.submitTextTurn(sessionId, req) as unknown as Promise<TurnResponse>;
    pendingTextMutation.current = { sessionId, promise };
    try { return await promise; } finally { if (pendingTextMutation.current?.promise === promise) pendingTextMutation.current = null; }
  }
  async function proposeClaim(): Promise<void> {
    const s = requireReady();
    if (!s.activeChallenge) throw new Error('Request a specific challenge input first.');
    const exercise = exercises.find(item => item.exercise_id === s.exerciseId);
    const outputKind = exercise?.output_schema?.kind ?? 'integer';
    const prediction = parsePrediction(predictedValue, outputKind);
    const text = `It returns ${formatPrediction(prediction)}${predictionReason.trim() ? ` because ${predictionReason.trim()}` : ''}`;
    const epoch = generation.current;
    const res = await sendTrackedText(s.sessionId, { text, revision: s.revision, challenge_id: s.activeChallenge.challenge_id });
    if (isCurrent(epoch, s)) applyTurn(res, text);
  }
  async function proposeTranscript(): Promise<void> {
    const s = requireReady();
    if (!s.editableTranscript.trim()) throw new Error('Type or record an explanation first.');
    const epoch = generation.current;
    const res = await sendTrackedText(s.sessionId, { text: s.editableTranscript, revision: s.revision, challenge_id: s.activeChallenge?.challenge_id });
    if (isCurrent(epoch, s)) { applyTurn(res, s.editableTranscript); if (route.problemId) await speakConversation(res); }
  }
  async function confirmClaim(): Promise<void> {
    const s = requireReady();
    if (!s.proposedClaim || !s.activeTurnId) throw new Error('Propose and review an interpretation before confirming.');
    const claim = confirmedInterpretation(s.proposedClaim, s.activeChallenge, predictedValue, predictionReason);
    const epoch = generation.current;
    if (claim.claim_type === 'OUTPUT_PREDICTION_AND_REASON') setWorkbench(prev => ({ ...prev, learningState: 'VERIFYING', activeView: 'ISOLATED_VERIFICATION_PROGRESS' }));
    const res = await api.confirmTurnClaim(s.sessionId, s.activeTurnId, { revision: s.revision, challenge_id: claim.challenge_id ?? undefined, capture_attempt_id: s.captureAttemptId, claim }) as unknown as ResultResponse;
    if (!isCurrent(epoch, s)) return;
    if (res.artifact && !res.challenge && !res.diagnostic_challenge && s.activeChallenge && res.executed !== false) {
      const snapshot = await api.restoreSession(s.sessionId);
      if (isCurrent(epoch, s)) applySnapshot(snapshot, s.sessionToken!);
    } else { const next = applyServerResult(latest.current, res); setWorkbench(next); if (res.coaching) queueAutoReply(next); }
  }
  async function verifyRepair(): Promise<void> {
    const s = requireReady(); const epoch = generation.current;
    setWorkbench(prev => ({ ...prev, learningState: 'VERIFYING', activeView: 'ISOLATED_VERIFICATION_PROGRESS' }));
    const spec = exercises.find(e => e.exercise_id === s.exerciseId)?.spec_versions.find(item => item.spec_version === s.specVersion);
    const target = spec?.recommended_generated_cases ?? 100;
    const res = await api.verifyRepair(s.sessionId, { revision: s.revision, prior_artifact_id: s.priorFailureArtifactId, run_curated_suite: true, generated_cases_target: target });
    if (isCurrent(epoch, s)) setWorkbench(prev => applyServerResult(prev, res));
  }
  async function retryExecution(): Promise<void> {
    const s = requireReady(); if (!s.activeTurnId) throw new Error('Restore the unavailable turn before retrying execution.');
    const epoch = generation.current;
    setWorkbench(prev => ({ ...prev, learningState: 'VERIFYING', activeView: 'ISOLATED_VERIFICATION_PROGRESS' }));
    const res = await api.retryExecution(s.sessionId, s.activeTurnId, { revision: s.revision });
    if (isCurrent(epoch, s)) setWorkbench(prev => applyServerResult(prev, res));
  }
  async function requestHint(level: HintLevel): Promise<void> {
    const s = requireReady(); if (!s.activeArtifact || s.diagnosticHidden) throw new Error('Confirm the diagnostic prediction and inspect its result first.');
    const highest = Math.max(0, ...s.coachingHistory.filter(item => !item.stale).map(item => item.hintLevel));
    if (level !== highest + 1) throw new Error('Request hints in sequence.');
    const epoch = generation.current;
    const res = await api.requestCoachingHint(s.sessionId, { artifact_id: s.activeArtifact.artifact_id, requested_level: level, revision: s.revision }) as CoachingResponse;
    if (!isCurrent(epoch, s)) return;
    const next = { ...latest.current, currentHintLevel: level, coachingHistory: [...latest.current.coachingHistory, coachingEntry(res, level)] };
    setWorkbench(next); queueAutoReply(next);
  }
  async function cancel(): Promise<void> {
    const s = latest.current;
    const pending = pendingTextMutation.current?.sessionId === s.sessionId ? pendingTextMutation.current.promise : null;
    void interruptLocal('Learner cancelled turn', false, false);
    const epoch = generation.current;
    setWorkbench(prev => ({ ...prev, activeTurnId: null, proposedClaim: null, activeChallenge: null }));
    const mutation = pending ? await pending.catch(() => null) : null;
    if (!s.sessionId || generation.current !== epoch || latest.current.sessionId !== s.sessionId) return;
    await api.cancelSessionWork(s.sessionId, { scope: 'TURN', turn_id: mutation?.turn_id ?? s.activeTurnId, reason: 'Learner cancelled turn' });
    const snapshot = await api.restoreSession(s.sessionId);
    if (generation.current !== epoch || latest.current.sessionId !== s.sessionId || latest.current.editorDirty) return;
    const cancelledChallenge = mutation?.proposed_claim.challenge_id ?? s.activeChallenge?.challenge_id;
    applySnapshot({ ...snapshot, challenges: snapshot.challenges.filter(item => item.challenge_id !== cancelledChallenge) }, s.sessionToken!);
  }
  async function bargeIn(): Promise<void> {
    stopAudioPlayback();
    interruptedReply.current = true;
    setVoiceMessage('Listening. Your words are kept when you interrupt.');
  }
  async function speakConversation(turn: TurnResponse): Promise<void> {
    const s = latest.current;
    const textResponse = await fetch(`/api/v1/sessions/${s.sessionId}/conversation/text`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${s.sessionToken}`, 'X-Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify({ revision: turn.revision, turn_id: turn.turn_id }),
    });
    if (!textResponse.ok) throw new Error('Your explanation is saved, but the mentor reply could not be loaded. Retry or continue editing.');
    const reply: unknown = await textResponse.json();
    if (typeof reply !== 'object' || reply === null || !('text' in reply) || typeof reply.text !== 'string') throw new Error('Mentor returned an invalid text response.');
    if (latest.current.activeTurnId !== turn.turn_id || !sameRevision(latest.current.revision, turn.revision)) return;
    appendConversation({ id: `mentor-${turn.turn_id}-${turn.capture_attempt_id}`, speaker: 'mentor', text: reply.text });
    if (!shouldRequestVoice(audioPreferencesRef.current) || !audioPreferencesRef.current.autoSpeak) return;
    const controller = new AbortController();
    speechRequest.current = controller; speechRequestPurpose.current = 'TTS';
    try {
    const response = await fetch(`/api/v1/sessions/${s.sessionId}/speech/conversation`, {
      method: 'POST', signal: controller.signal,
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${s.sessionToken}`, 'X-Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify({ revision: turn.revision, turn_id: turn.turn_id }),
    });
    if (!response.ok) throw new Error('Mentor voice is unavailable. Your explanation is saved; use Transcript & text if needed.');
    const text = response.headers.get('X-Coach-Text');
    if (text) setVoiceMessage(decodeURIComponent(text));
    const bytes = await response.arrayBuffer();
    if (controller.signal.aborted || s.sessionId !== latest.current.sessionId || (recorder.current?.isRecording && Date.now() - lastSpeechAt.current < 1200)) return;
    interruptedReply.current = false; // Speaking is driven by the actual audio player, not network completion.
    await voice.current.play({ wavBytes: bytes, playbackId: response.headers.get('X-Playback-ID') ?? undefined,
      sessionId: s.sessionId!, turnId: turn.turn_id, turnGeneration: turn.revision.turn_generation, revision: turn.revision,
      onEnded: () => { setSpeaking(false); if (speechRequest.current === controller) { speechRequest.current = null; speechRequestPurpose.current = null; } }, onAutoplayBlocked: () => { setSpeaking(false); if (speechRequest.current === controller) { speechRequest.current = null; speechRequestPurpose.current = null; } setVoiceMessage('Tap the microphone to enable audio. Your explanation is saved.'); } }, controller.signal);
    } catch (err) {
      if (speechRequest.current === controller) { speechRequest.current = null; speechRequestPurpose.current = null; setSpeaking(false); }
      throw err;
    }
  }
  async function finishVoiceTurn(): Promise<void> {
    if (voiceSubmitting.current) {
      pendingVoiceFlush.current = true;
      const capture = recorder.current;
      if (capture && !capture.isRecording && capture.capturedSamplesCount > 0) {
        const segment = capture.drainMicrophoneCapture();
        if (!segment.lowEnergyWarning) queuedVoiceSegments.current = [...queuedVoiceSegments.current, segment.wavBytes];
      }
      return;
    }
    pendingVoiceFlush.current = false;
    const s = requireReady();
    const capture = recorder.current;
    const queued = queuedVoiceSegments.current[0];
    if (!retainedAudio.current && queued) { retainedAudio.current = queued; queuedVoiceSegments.current = queuedVoiceSegments.current.slice(1); }
    if (!retainedAudio.current && (!capture || capture.capturedSamplesCount === 0)) return;
    const segment = retainedAudio.current ? null : capture?.drainMicrophoneCapture();
    if (segment?.lowEnergyWarning) return;
    const wav = retainedAudio.current ?? segment!.wavBytes;
    if (wav.byteLength <= 44) return;
    retainedAudio.current = wav; voiceSubmitting.current = true;
    const epoch = generation.current;
    const data = new FormData();
    data.append('audio', new Blob([new Uint8Array(wav)], { type: 'audio/wav' }), 'reasoning.wav');
    data.append('revision', JSON.stringify(s.revision));
    if (s.activeChallenge?.reveal_state === 'HIDDEN') data.append('challenge_id', s.activeChallenge.challenge_id);
    data.append('language_mode', s.languageMode);
    data.append('capture_attempt_id', String(s.captureAttemptId));
    const controller = new AbortController(); voiceUploadRequest.current = controller; speechRequest.current = controller; speechRequestPurpose.current = 'STT';
    try {
      const response = await fetch(`/api/v1/sessions/${s.sessionId}/turns/audio`, { method: 'POST', signal: controller.signal,
        headers: { Authorization: `Bearer ${s.sessionToken}`, 'X-Idempotency-Key': crypto.randomUUID() }, body: data });
      if (!response.ok) {
        const detail: unknown = await response.json().catch(() => null);
        const message = detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string' ? detail.message : `Recognition unavailable (${response.status}).`;
        throw new Error(`${message} Your audio is retained; tap Retry or Send voice to retry.`);
      }
      let turn = await response.json() as TurnResponse;
      if (controller.signal.aborted || epoch !== generation.current || s.sessionId !== latest.current.sessionId || latest.current.editorDirty) return;
      retainedAudio.current = null;
      let transcript = turn.normalized_transcript ?? turn.transcript ?? '';
      // Publish each authoritative generation in order before issuing the next mutation.
      applyTurn(turn, transcript);
      if (interruptedReply.current && s.editableTranscript.trim()) {
        transcript = `${s.editableTranscript} ${transcript}`;
        turn = await sendTrackedText(s.sessionId, { text: transcript, revision: turn.revision, challenge_id: s.activeChallenge?.reveal_state === 'HIDDEN' ? s.activeChallenge.challenge_id : undefined });
        if (epoch !== generation.current || s.sessionId !== latest.current.sessionId || latest.current.editorDirty) return;
        applyTurn(turn, transcript);
      }
      capture?.setTurnGeneration(turn.revision.turn_generation, true);
      if (voiceUploadRequest.current === controller) { voiceSubmitting.current = false; voiceUploadRequest.current = null; }
      if (pendingVoiceFlush.current || queuedVoiceSegments.current.length > 0) { await finishVoiceTurn(); return; }
      await speakConversation(turn);
    } catch (err) {
      if (!controller.signal.aborted && retainedAudio.current === wav && isCurrent(epoch, s)) {
        // Allocating a voice turn can advance the server revision even when recognition fails.
        // Recover only matching saved code; never restore over buffered speech or a newer edit.
        try {
          const snapshot = await api.restoreSession(s.sessionId);
          if (isCurrent(epoch, s)) {
            const next = reconcileVoiceRetry(latest.current, snapshot);
            if (!next) throw new Error('The saved code or session changed. The recording cannot be retried against a different revision.');
            latest.current = next; setWorkbench(next);
            capture?.setTurnGeneration(next.turnGeneration, true);
          }
        } catch (recoveryError) {
          throw new Error(`${err instanceof Error ? err.message : 'Recognition failed; your audio is retained.'} Could not synchronize the retry: ${recoveryError instanceof Error ? recoveryError.message : 'Session recovery unavailable.'}`);
        }
      }
      throw err;
    } finally {
      if (voiceUploadRequest.current === controller) { voiceSubmitting.current = false; voiceUploadRequest.current = null; }
      if (speechRequest.current === controller) { speechRequest.current = null; speechRequestPurpose.current = null; }
    }
  }
  async function microphone(): Promise<void> {
    void voice.current.unlockAudioFromGesture();
    if (audioPreferencesRef.current.textOnly) {
      updateAudio({ textOnly: false, voiceOutput: true, autoSpeak: true, muted: false });
    }
    const s = requireReady();
    const captureAttempt = captureCancellation.current;
    const validCapture = () => captureCancellation.current === captureAttempt && !audioPreferencesRef.current.textOnly;
    stopAudioPlayback();
    if (recorder.current?.isRecording && sttTransport === 'REST') { await finishVoiceTurn(); return; }
    if (retainedAudio.current && sttTransport === 'REST') { await finishVoiceTurn(); return; }
    if (recorder.current?.isRecording) {
      const attemptGeneration = generation.current;
      const wav = await recorder.current.stopMicrophoneCapture();
      if (!isCurrent(attemptGeneration, s) || !validCapture()) return;
      setRecording(false);
      if (liveSocket.current && frameWriter.current && socketResult.current) {
        frameWriter.current.finish(); liveSocket.current.send(JSON.stringify({ type: 'commit' }));
        const result = await socketResult.current;
        if (!isCurrent(attemptGeneration, s) || !validCapture()) return;
        liveSocket.current?.close(); liveSocket.current = null; frameWriter.current = null;
        applyTurn(result, result.normalized_transcript ?? result.transcript ?? '');
        return;
      }
      const data = new FormData(); data.append('audio', new Blob([new Uint8Array(wav.wavBytes)], { type: 'audio/wav' }), 'prediction.wav');
      data.append('revision', JSON.stringify(s.revision)); if (s.activeChallenge) data.append('challenge_id', s.activeChallenge.challenge_id);
      data.append('language_mode', s.languageMode); data.append('turn_generation', String(s.turnGeneration)); data.append('capture_attempt_id', String(s.captureAttemptId));
      const controller = new AbortController(); speechRequest.current = controller; speechRequestPurpose.current = 'STT';
      const response = await fetch(`/api/v1/sessions/${s.sessionId}/turns/audio`, { signal: controller.signal, method: 'POST', headers: { Authorization: `Bearer ${s.sessionToken}`, 'X-Idempotency-Key': crypto.randomUUID() }, body: data });
      if (!response.ok) throw new Error(`Speech recognition unavailable (HTTP ${response.status}). You can type your prediction.`);
      const res = await response.json() as TurnResponse;
      if (generation.current !== attemptGeneration || latest.current.editorDirty || latest.current.sessionId !== s.sessionId || !validCapture()) return;
      applyTurn(res, res.normalized_transcript ?? res.transcript ?? '');
      return;
    }
    generation.current++;
    const captureEpoch = generation.current;
    if (!recorder.current) recorder.current = new AudioRecorder(s.sessionId, s.turnGeneration);
    recorder.current.setTurnGeneration(s.turnGeneration);
    try {
      if (sttTransport === 'WS') {
        const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/v1/sessions/${s.sessionId}/speech/ws`);
        liveSocket.current = socket;
        socketResult.current = new Promise<TurnResponse>((resolve, reject) => {
          const timeout = setTimeout(() => { socket.close(); reject(new Error('WebSocket recognition timed out. Use REST or typed input.')); }, 45_000);
          socket.addEventListener('message', message => {
            try {
              const result = JSON.parse(String(message.data));
              if (result.type === 'error') throw new Error(result.message ?? 'WebSocket recognition failed.');
              if (result.proposed_claim) { clearTimeout(timeout); resolve(result as TurnResponse); }
            } catch (err) { clearTimeout(timeout); reject(err); }
          });
          socket.addEventListener('error', () => { clearTimeout(timeout); reject(new Error('WebSocket recognition unavailable. Select REST or typed input.')); });
          socket.addEventListener('close', () => { clearTimeout(timeout); reject(new DOMException('Recognition connection closed', 'AbortError')); });
        });
        void socketResult.current.catch(() => undefined);
        await new Promise<void>((resolve, reject) => {
          const timeout = setTimeout(() => { socket.close(); reject(new Error('WebSocket connection timed out.')); }, 8000);
          socket.addEventListener('open', () => { clearTimeout(timeout); if (!isCurrent(captureEpoch, s) || !validCapture()) { reject(new DOMException('Capture cancelled', 'AbortError')); return; } socket.send(JSON.stringify({ token: s.sessionToken, revision: s.revision, challenge_id: s.activeChallenge?.challenge_id, language_mode: s.languageMode, turn_generation: s.turnGeneration, capture_attempt_id: s.captureAttemptId + 1 })); resolve(); }, { once: true });
          socket.addEventListener('error', () => { clearTimeout(timeout); reject(new Error('WebSocket connection failed.')); }, { once: true });
          socket.addEventListener('close', () => { clearTimeout(timeout); reject(new DOMException('Recognition connection closed', 'AbortError')); }, { once: true });
        });
        if (!isCurrent(captureEpoch, s) || !validCapture()) { socket.close(); return; }
        frameWriter.current = new PcmFrameWriter(frame => { if (socket.readyState !== WebSocket.OPEN || socket.bufferedAmount > 131072) throw new Error('Speech stream backpressure limit reached.'); socket.send(new Uint8Array(frame)); });
      }
      const capture = recorder.current;
      await capture.startMicrophoneCapture({
        onSpeechActivity: () => {
          if (!validCapture() || latest.current.sessionId !== s.sessionId) return;
          lastSpeechAt.current = Date.now();
          if (voiceSubmitting.current || speechRequestPurpose.current === 'TTS') { interruptedReply.current = true; stopAudioPlayback(); }
        },
        onSilenceTimeout: () => { if (validCapture() && latest.current.sessionId === s.sessionId && sttTransport === 'REST') void perform(finishVoiceTurn); },
        onFrameTelemetry: f => { if (latest.current.sessionId !== s.sessionId || !validCapture()) return; setRms(f.rmsNormalized); try { frameWriter.current?.push(f.pcm16); } catch (err) { fail(err); liveSocket.current?.close(); void recorder.current?.dispose(); setRecording(false); } }, onDeviceLost: () => { if (!isCurrent(captureEpoch, s) || !validCapture()) return; setRecording(false); setWorkbench(prev => ({ ...prev, interactionMode: 'TYPED_FALLBACK' })); }, onBackpressureLimitReached: () => { if (sttTransport === 'REST') void perform(finishVoiceTurn); else void perform(microphone); } });
      if (!isCurrent(captureEpoch, s) || !validCapture()) { await capture.dispose(); return; }
      setRecording(true); setWorkbench(prev => ({ ...prev, micChecked: true, captureAttemptId: s.captureAttemptId + 1, interactionMode: 'VOICE', proposedClaim: null }));
    } catch (err) { if (!isCurrent(captureEpoch, s) || !validCapture()) return; liveSocket.current?.close(); frameWriter.current = null; setWorkbench(prev => ({ ...prev, interactionMode: 'TYPED_FALLBACK', activeView: 'QUEUE_DEGRADATION_RECOVERY' })); throw err; }
  }
  async function deletePractice(): Promise<void> {
    const s = latest.current;
    await cancel(); const epoch = generation.current;
    if (s.sessionId) await api.deleteSession(s.sessionId);
    if (epoch !== generation.current || latest.current.sessionId !== s.sessionId) return;
    stopAudioPlayback(); stopSpeechCapture(); voice.current.clearReplay();
    setAutoVoiceRequest(null); orientationCache.current = null; voiceReplayRevision.current = null; setHasVoiceReplay(false);
    setPredictedValue(''); setPredictionReason('');
    sessionStorage.removeItem(RESTORE_KEY); forgetTabSession(s.exerciseId, s.specVersion);
    const key = draftKey(s.exerciseId, s.specVersion);
    const nextProduct = { ...productRef.current, drafts: Object.fromEntries(Object.entries(productRef.current.drafts).filter(([id]) => id !== key)) };
    productRef.current = nextProduct; setProduct(nextProduct); setStorageWarning(saveProductState(nextProduct));
    const starter = exercises.find(e => e.exercise_id === s.exerciseId)?.starter_code ?? '';
    setWorkbench({ ...createInitialWorkbenchState(), exerciseId: s.exerciseId, specVersion: s.specVersion, sourceCode: starter, persistedSourceCode: starter, languageMode: nextProduct.language, specAcknowledged: s.specVersion !== 'v2_negatives_allowed' });
  }
  async function playOrientation(purpose: 'introduction' | 'test-voice', state = latest.current): Promise<void> {
    if (!shouldRequestVoice(audioPreferencesRef.current)) { setVoiceMessage('Audio is off. Read the statement or coach text instead.'); return; }
    if (!state.sessionId || !state.revision) throw new Error('Start a practice session before testing its voice.');
    const epoch = generation.current;
    const controller = new AbortController(); speechRequest.current?.abort(); speechRequest.current = controller; speechRequestPurpose.current = 'TTS';
    const key = `${state.sessionId}:${state.revision.code_hash}:${purpose}`;
    const cached = orientationCache.current;
    const data = cached?.key === key ? cached : await api.requestVoiceOrientation(state.sessionId, state.revision, purpose, controller.signal);
    if (generation.current !== epoch || controller.signal.aborted || latest.current.sessionId !== state.sessionId || !shouldRequestVoice(audioPreferencesRef.current)) return;
    orientationCache.current = { key, ...data }; voiceReplayRevision.current = state.revision; setHasVoiceReplay(true);
    playbackPurpose.current = 'orientation';
    const result = await voice.current.play({ wavBytes: data.audio, playbackId: data.playbackId ?? undefined, sessionId: state.sessionId, turnId: `orientation-${purpose}`, turnGeneration: state.turnGeneration, revision: state.revision, onEnded: () => { setSpeaking(false); if (speechRequest.current === controller) { speechRequest.current = null; speechRequestPurpose.current = null; } }, onAutoplayBlocked: () => { setSpeaking(false); if (speechRequest.current === controller) { speechRequest.current = null; speechRequestPurpose.current = null; } setVoiceMessage('Tap the microphone to enable audio on this browser.'); } }, controller.signal);
    if (!result.started) setSpeaking(false);
    setVoiceMessage(result.started ? 'Voice playing. Stop audio any time; your text stays available.' : 'Playback did not start. Read the text or use local replay.');
  }
  function chooseInput(choice: 'text' | 'voice'): void {
    if (choice === 'voice') {
      void voice.current.unlockAudioFromGesture().then(unlocked => setVoiceMessage(unlocked ? 'Voice is enabled. Choose record, play, or test voice when ready.' : 'Voice is enabled. If playback is blocked, read the text or retry after a page interaction.')).catch(fail);
    }
    setProduct(prev => ({ ...prev, inputChoice: choice }));
    updateAudio({ textOnly: choice === 'text', voiceOutput: choice === 'voice', autoSpeak: choice === 'voice', introductions: choice === 'voice', muted: false });
    setWorkbench(prev => ({ ...prev, interactionMode: choice === 'text' ? 'TYPED_FALLBACK' : 'VOICE' }));
  }
  function queueAutoReply(next: WorkbenchSessionState): void {
    if (audioPreferencesRef.current.autoSpeak && shouldRequestVoice(audioPreferencesRef.current) && next.activeArtifact && next.activeTurnId && !next.editorDirty && !next.diagnosticHidden) setAutoVoiceRequest(next.revision);
  }
  useEffect(() => {
    if (!autoVoiceRequest) return;
    setAutoVoiceRequest(null);
    if (sameRevision(autoVoiceRequest, workbench.revision) && shouldRequestVoice(audioPreferencesRef.current)) void effectActions.current.playCoach().catch(fail);
  }, [autoVoiceRequest, workbench.revision, audioPreferences, ttsTransport]);
  function updateAudio(patch: Partial<AudioPreferences>): void {
    const next = updateAudioPreferences(audioPreferencesRef.current, patch);
    audioPreferencesRef.current = next; setAudioPreferences(next);
    if (!shouldRequestVoice(next)) stopAudioPlayback();
    if (next.textOnly) stopSpeechCapture();
    if (next.textOnly) setWorkbench(prev => ({ ...prev, interactionMode: 'TYPED_FALLBACK' }));
  }
  async function replayVoice(): Promise<void> {
    if (!sameRevision(voiceReplayRevision.current, latest.current.revision) || latest.current.editorDirty || !shouldRequestVoice(audioPreferencesRef.current)) return;
    stopAudioPlayback(); playbackPurpose.current = 'replay';
    const controller = new AbortController(); speechRequest.current?.abort(); speechRequest.current = controller; speechRequestPurpose.current = 'TTS';
    const s = latest.current; const epoch = generation.current;
    try { await voice.current.replay(controller.signal); }
    finally { if (isCurrent(epoch, s)) setCoachReplayKeys(prev => prev.filter(cachedKey => voice.current.hasReplay(cachedKey))); }
  }
  async function playCoach(hintLevel?: HintLevel): Promise<void> {
    if (!shouldRequestVoice(audioPreferencesRef.current)) { setVoiceMessage('Audio is off. Read the coach text instead.'); return; }
    const s = requireReady(); if (!s.activeArtifact || !s.activeTurnId || s.diagnosticHidden || !s.specAcknowledged || !sameRevision(s.activeArtifact.revision, s.revision)) throw new Error('A revealed coaching result is required.');
    const level = hintLevel ?? s.currentHintLevel;
    if (!s.coachingHistory.some(item => !item.stale && item.hintLevel === level)) throw new Error('This coaching message is not unlocked for the active result.');
    const key = coachReplayKey(s, level);
    const requestGeneration = generation.current;
    stopAudioPlayback();
    playbackPurpose.current = 'coach';
    const controller = new AbortController(); speechRequest.current?.abort(); speechRequest.current = controller; speechRequestPurpose.current = 'TTS';
    if (voice.current.hasReplay(key)) {
      if (!isCurrent(requestGeneration, s) || latest.current.activeArtifact?.artifact_id !== s.activeArtifact.artifact_id) return;
      playbackPurpose.current = 'replay';
      voiceReplayRevision.current = s.revision; setHasVoiceReplay(true);
      try { await voice.current.replay(controller.signal, key); }
      finally { if (isCurrent(requestGeneration, s)) setCoachReplayKeys(prev => prev.filter(cachedKey => voice.current.hasReplay(cachedKey))); }
      return;
    }
    const response = await fetch(`/api/v1/sessions/${s.sessionId}/speech/${ttsTransport === 'STREAM' ? 'tts-stream' : 'tts'}`, { signal: controller.signal, method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${s.sessionToken}`, 'X-Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify({ revision: s.revision, artifact_id: s.activeArtifact.artifact_id, hint_level: level }) });
    if (!response.ok) throw new Error(`Voice playback unavailable (HTTP ${response.status}). Read the coach text below.`);
    if (!isCurrent(requestGeneration, s) || latest.current.activeArtifact?.artifact_id !== s.activeArtifact.artifact_id || controller.signal.aborted || !shouldRequestVoice(audioPreferencesRef.current)) { controller.abort(); return; }
    // Local replay must not re-deliver an older hint or advance server progression.
    let deliveryAcknowledged = false;
    const acknowledge = (ack: VoicePlaybackAckRequest) => {
      if (deliveryAcknowledged || !isCurrent(requestGeneration, s) || latest.current.activeArtifact?.artifact_id !== s.activeArtifact?.artifact_id) return;
      deliveryAcknowledged = true;
      if (ack.playback_id) void api.sendPlaybackAck(s.sessionId, { playback_id: ack.playback_id, playback_status: ack.playback_status, played_duration_ms: ack.played_duration_ms ?? 0, revision: s.revision }).catch(err => { if (isCurrent(requestGeneration, s)) fail(err); });
    };
    if (ttsTransport === 'STREAM') {
      await streamedPlayer.current?.stop();
      const streaming = new StreamingPcmPlayer(s.revision); streaming.setPreferences(audioPreferencesRef.current); streamedPlayer.current = streaming;
      let playbackId = response.headers.get('X-Playback-ID') ?? '';
      const started = performance.now();
      try {
        await consumeAudioEvents(response, async event => { if (!isCurrent(requestGeneration, s)) throw new DOMException('Playback interrupted', 'AbortError'); if (event.playback_id) playbackId = event.playback_id; await streaming.append(event); }, controller.signal);
        await streaming.finish();
        if (playbackId) acknowledge({ session_id: s.sessionId, turn_id: s.activeTurnId, turn_generation: s.turnGeneration, playback_id: playbackId, playback_status: 'COMPLETED', played_duration_ms: Math.round(performance.now() - started) });
      } catch (err) {
        if (playbackId) acknowledge({ session_id: s.sessionId, turn_id: s.activeTurnId, turn_generation: s.turnGeneration, playback_id: playbackId, playback_status: controller.signal.aborted ? 'INTERRUPTED' : 'READ_TEXT_FALLBACK', played_duration_ms: Math.round(performance.now() - started) });
        throw err;
      } finally { await streaming.stop(); if (streamedPlayer.current === streaming) streamedPlayer.current = null; }
    } else {
      const bytes = await response.arrayBuffer();
      if (!isCurrent(requestGeneration, s) || latest.current.activeArtifact?.artifact_id !== s.activeArtifact.artifact_id || controller.signal.aborted || !shouldRequestVoice(audioPreferencesRef.current)) return;
      voiceReplayRevision.current = s.revision; setHasVoiceReplay(true);
      await voice.current.play({ wavBytes: bytes, playbackId: response.headers.get('X-Playback-ID') ?? undefined, sessionId: s.sessionId, turnId: s.activeTurnId, turnGeneration: s.turnGeneration, revision: s.revision, onEnded: acknowledge, onAutoplayBlocked: ack => { acknowledge(ack); if (isCurrent(requestGeneration, s)) setVoiceMessage('Playback blocked. Read the coach text or replay locally.'); } }, controller.signal, key, s.activeArtifact.artifact_id);
      if (isCurrent(requestGeneration, s)) setCoachReplayKeys(prev => [...new Set([...prev, key])].filter(cachedKey => voice.current.hasReplay(cachedKey)));
    }
  }
  async function checkMicrophone(): Promise<void> {
    if (audioPreferencesRef.current.textOnly) return;
    generation.current++;
    const epoch = generation.current;
    await recorder.current?.dispose();
    const check = new AudioRecorder('microphone-setup'); recorder.current = check;
    setWorkbench(prev => ({ ...prev, activeView: 'ONBOARDING_MIC_CHECK' }));
    try {
      await check.startMicrophoneCapture({ onFrameTelemetry: frame => { if (epoch === generation.current) setRms(frame.rmsNormalized); } });
      if (epoch !== generation.current) return;
      setMicMessage('Listening for two seconds. This setup recording stays in memory and is discarded.');
      await new Promise(resolve => setTimeout(resolve, 2000));
      if (epoch !== generation.current) return;
      const sample = await check.stopMicrophoneCapture();
      setMicMessage(sample.lowEnergyWarning ? 'Microphone opened; sound level was low. Check your input device or use typed input.' : 'Microphone opened and audio frames were captured. You can now record a prediction.');
      setWorkbench(prev => ({ ...prev, micChecked: true, interactionMode: 'VOICE' }));
    } catch (err) {
      setWorkbench(prev => ({ ...prev, interactionMode: 'TYPED_FALLBACK' }));
      throw err;
    } finally { await check.dispose(); if (recorder.current === check) recorder.current = null; }
  }
  useEffect(() => {
    if (loading || !route.problemId || workbench.exerciseId !== route.problemId || !exercises.length) return;
    const key = `${route.problemId}:${workbench.specVersion}`;
    if (openingKey.current === key) return;
    openingKey.current = key;
    setProduct(prev => ({ ...prev, coachCollapsed: false }));
    void effectActions.current.perform(async () => {
      if (!latest.current.sessionId) await effectActions.current.startSession();
      else if (shouldPlayIntroduction(audioPreferencesRef.current)) await effectActions.current.playOrientation('introduction');
    });
  }, [loading, route.problemId, workbench.exerciseId, workbench.specVersion, exercises.length]);
  const executionReadiness = health?.custom_code_execution_enabled && health.execution_status !== 'BLOCKED_EXTERNAL' && health.execution_status !== 'DISABLED' ? 'Accepted isolated runtime ready' : health?.execution_status === 'BLOCKED_EXTERNAL' ? 'Execution blocked by external isolation readiness' : health?.execution_status === 'DISABLED' ? 'Custom execution disabled' : 'Custom execution not accepted / unavailable';
  const currentExercise = exercises.find(e => e.exercise_id === workbench.exerciseId);
  const verification = !workbench.editorDirty && sameRevision(workbench.activeVerificationReport?.revision, workbench.revision) ? workbench.activeVerificationReport?.report ?? null : null;
  const trace = workbench.editorDirty ? null : workbench.activeTrace;
  const traceLine = trace?.steps?.[workbench.selectedTraceStepIndex]?.source_line ?? null;
  const isLibrary = !route.problemId;
  const stageCopy: Record<string, string> = { EXERCISE_BRIEF_SPEC: 'Read the problem, then start practicing.', DOMAIN_SHIFT_ACK_GATE: 'Review and acknowledge this specification.', EXPLAIN_APPROACH_TURN: 'Explain your approach, or choose a challenge input.', PREDICT_CHALLENGE_OUTPUT: 'Predict the output before running.', TRANSCRIPT_CLAIM_CONFIRMATION: 'Your explanation is saved. Continue talking, or submit your code when ready.', ISOLATED_VERIFICATION_PROGRESS: 'Checking your confirmed claim…', REVEALED_COMPARISON_VIEW: 'Inspect what happened. Prediction and correctness are separate.', TRACE_SCRUBBER_INSPECTION: 'Follow the trace, then make a repair.', SOCRATIC_HINT_PROGRESSION: 'Use one hint at a time to guide your repair.', FRESH_TRANSFER_CHALLENGE: 'Try a fresh input to check your reasoning.', PRACTICE_CHECKPOINT_SUMMARY: 'Bounded practice checkpoint completed, not proven mastery.', QUEUE_DEGRADATION_RECOVERY: 'The service is unavailable. Your draft is safe.', ONBOARDING_MIC_CHECK: 'Microphone setup is optional.' };
  return <div className={`app-shell ${isLibrary ? 'library-shell' : 'practice-shell'}`}>
    <a className="skip-link" href="#main-content">Skip to main content</a>
    <WorkspaceHeader productName={branding.productName} shortName={branding.shortName} title={currentExercise?.title} isLibrary={isLibrary} collapsed={product.coachCollapsed} onLibrary={() => openLibrary()} onSettings={() => setSettingsOpen(true)} onToggleCoach={() => setProduct(prev => ({ ...prev, coachCollapsed: !prev.coachCollapsed }))} />
    {loading && <p className="loading-state" role="status">Loading workspace metadata...</p>}
    {error && <div className="app-error" role="alert" tabIndex={-1} ref={errorFocus}><span>{error}</span> <div className="button-row"><button onClick={() => { if (retainedAudio.current) void perform(microphone); else setRetry(n => n + 1); }}>Retry</button><button className="error-dismiss" onClick={() => setError(null)} aria-label="Dismiss error">✕</button></div></div>}
    {storageWarning && <p className="storage-warning" role="status">{storageWarning}</p>}
    {!loading && <main id="main-content" className={isLibrary ? 'library-main' : 'practice-main'} ref={pageFocus} tabIndex={-1}>
      {isLibrary ? <ProblemLibrary exercises={exercises} route={route} product={product} onRouteChange={next => navigate(next)} onOpen={(problem, spec) => { void openProblem(problem, spec).catch(fail); }} onBookmark={problem => setProduct(prev => ({ ...prev, bookmarks: prev.bookmarks.includes(problem) ? prev.bookmarks.filter(id => id !== problem) : [...prev.bookmarks, problem] }))} /> : <>
        {!route.problemId && !product.inputChoice && !product.alwaysVoiceOn && <section className="input-choice" aria-label="Choose your practice mode"><div><h2>How would you like to practice?</h2><p>Text is always available. Voice is optional and only starts when you choose it.</p></div><div className="button-row"><button className="primary" onClick={() => chooseInput('text')}>Text only</button><button onClick={() => chooseInput('voice')}>Voice coach</button></div></section>}
        <LearningStepIndicator state={workbench} />
        <div className="practice-toolbar"><p role="status" aria-live="polite">{busy ? 'Working…' : stageCopy[workbench.activeView]}{recording ? ` · Recording (${Math.round(rms * 100)}% level)` : ''}</p><div className="button-row"><span className="save-status">{workbench.editorDirty ? 'Draft · not saved to session' : workbench.sessionId ? 'Saved revision' : 'Starter code'}</span></div></div>
        <div className="mobile-pane-switch"><AccessibleTabs label="Workspace panes" controls={{ Statement: 'statement-pane', Code: 'code-pane', Coach: 'coach-pane', Results: 'results-pane' }} tabs={['Statement', 'Code', 'Coach', 'Results']} selected={mobilePane} onSelect={setMobilePane} /></div>
        <div className={`workspace-grid ${product.coachCollapsed ? 'coach-collapsed' : ''}`} data-mobile-pane={mobilePane} style={{ '--statement-width': `${product.statementWidth}px`, '--coach-width': `${product.coachWidth}px`, '--results-height': `${product.resultsHeight}px` } as React.CSSProperties}>
          <aside id="statement-pane" className="statement-pane" aria-label="Problem statement"><ProblemConstraintPanel exercise={currentExercise} state={workbench} onSelectSpec={spec => { void openProblem(workbench.exerciseId, spec).catch(fail); }} onAcknowledgeSpec={() => { void perform(async () => { const s = requireReady(); const epoch = generation.current; await api.acknowledgeSessionSpec(s.sessionId, { spec_version: s.specVersion, revision: s.revision }); const snapshot = await api.restoreSession(s.sessionId); if (isCurrent(epoch, s)) applySnapshot(snapshot, s.sessionToken!); }); }} /></aside>
          <div className="statement-resize"><ResizeHandle label="Resize problem statement" orientation="vertical" value={product.statementWidth} min={240} max={480} defaultValue={300} onChange={statementWidth => setProduct(prev => ({ ...prev, statementWidth }))} /></div>
          <CodeWorkspace state={workbench} highlightedLine={traceLine} onChangeCode={changeCode} onSaveCode={() => { void saveCode().catch(fail); }} onSubmitCode={() => { void perform(submitCode); }} isBusy={busy} />
          <div className="coach-resize"><ResizeHandle label="Resize coach" orientation="vertical" reverse value={product.coachWidth} min={300} max={520} defaultValue={360} onChange={coachWidth => setProduct(prev => ({ ...prev, coachWidth }))} /></div>
          {(() => {
            const activeTeacher = getTeacherForSubject(currentExercise?.collection);
            return (
          <aside id="coach-pane" className={`coach-pane mentor-panel-container ${recording ? 'is-recording' : ''} ${speaking ? 'is-speaking' : ''}`} aria-label="Learning coach">
            <div className="mentor-top-header">
              <div className="mentor-avatar-box">
                <img src={activeTeacher.avatarUrl} alt={activeTeacher.name} width="800" height="672" />
              </div>
              <div className="mentor-title-info">
                <h3>{activeTeacher.name}</h3>
                <p>
                  {speaking ? 'Speaking · interrupt anytime' : recording ? (
                    <>
                      Listening
                      <span className="sound-indicator"><span></span><span></span><span></span></span>
                    </>
                  ) : busy ? (
                    'Thinking…'
                  ) : !workbench.sessionId ? (
                    'Ready to start'
                  ) : (
                    'Ready when you are'
                  )}
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  const newMuted = !audioPreferences.muted;
                  updateAudio({ muted: newMuted, voiceOutput: !newMuted, autoSpeak: !newMuted });
                  if (!newMuted) {
                    void voice.current.unlockAudioFromGesture();
                    if (workbench.sessionId) {
                      void perform(() => playOrientation('test-voice'));
                    }
                  }
                }}
                aria-label={audioPreferences.muted ? 'Unmute voice' : 'Mute voice'}
                className="mentor-volume-btn"
                title={audioPreferences.muted ? 'Unmute mentor voice' : 'Mute mentor voice'}
              >
                {audioPreferences.muted ? '🔇' : '🔊'}
              </button>
            </div>

            {!workbench.sessionId && !busy && (
              <div className="start-session-hero">
                <div className="mentor-bubble">
                  <p>Hi Dhaanish. Today's challenge is <strong>"{currentExercise?.title ?? 'DSA Challenge'}"</strong>. Before any code, tell me in your own words what this is asking and how you would start. Speak or type, whichever feels natural.</p>
                </div>
                <button
                  type="button"
                  className="primary big-start-session-btn"
                  onClick={() => {
                    chooseInput('voice');
                    void perform(async () => {
                      await startSession();
                    });
                  }}
                  disabled={busy || !currentExercise}
                >
                  Start Practice Session
                </button>
                <p className="start-session-note">Text is always available. Voice is interactive and starts when you choose it.</p>
              </div>
            )}

            <ActiveConversation speaker={recording ? 'student' : conversationSpeaker} text={recording ? '' : conversationSpeaker === 'student' ? workbench.editableTranscript : mentorText || `Today's challenge is ${currentExercise?.title ?? 'your selected problem'}. What does it ask, and how would you begin?`} status={error ? 'error' : speaking ? 'playing' : recording ? 'listening' : busy ? 'thinking' : 'idle'} progress={audioProgress} history={conversation} />
            {workbench.sessionId && showTranscript && (
              <details className="mentor-chat-stream"><summary>Interpretation & grounded hints</summary>
                <div className="mentor-bubble">
                  <p>Hi Dhaanish. Today's challenge is <strong>"{currentExercise?.title ?? 'DSA Challenge'}"</strong>. Before any code, tell me in your own words what this is asking and how you would start. Speak or type, whichever feels natural.</p>
                </div>
                {workbench.editorDirty && <p className="notice">Save this revision before explaining or checking it. Previous evidence is superseded.</p>}
                {workbench.proposedClaim && (
                  <div className="mentor-bubble confirmation-bubble" aria-label="Editable claim interpretation">
                    <p>
                      <strong>Coach interpreted your approach:</strong>{' '}
                      {workbench.proposedClaim.claim_type === 'OUTPUT_PREDICTION_AND_REASON'
                        ? `Predicted output: ${formatPrediction(workbench.proposedClaim.predicted_output)}. Reason: ${workbench.proposedClaim.reason_summary ?? 'No reason provided'}.`
                        : workbench.proposedClaim.claim_type === 'INVARIANT_OR_MECHANISM_CLAIM'
                        ? workbench.proposedClaim.mechanism_summary
                        : workbench.proposedClaim.claim_type === 'DOMAIN_VALIDITY_CLAIM'
                        ? `Domain: ${workbench.proposedClaim.target_spec_version}`
                        : workbench.proposedClaim.claim_type === 'CLARIFICATION_OR_HINT_REQUEST'
                        ? workbench.proposedClaim.question_text
                        : workbench.proposedClaim.raw_summary ?? 'Review your explanation before confirming.'}
                    </p>
                  </div>
                )}
                <CoachingHintFeed
                  state={workbench}
                  isBusy={busy}
                  voiceEnabled={shouldRequestVoice(audioPreferences)}
                  replayableLevels={([1, 2, 3] as HintLevel[]).filter(level => coachReplayKeys.includes(coachReplayKey(workbench, level)))}
                  onPlayMessage={level => { void perform(() => playCoach(level)); }}
                  onRequestHintLevel={level => { void perform(() => requestHint(level)); }}
                  onSelectTracePointer={(eventId, line) => {
                    const index = workbench.activeTrace?.steps?.findIndex(step => eventId !== null ? step.event_id === eventId : step.source_line === line) ?? -1;
                    if (index >= 0) {
                      setResultPane('Evidence');
                      setMobilePane('Results');
                      setWorkbench(prev => ({ ...prev, selectedTraceStepIndex: index, activeView: 'TRACE_SCRUBBER_INSPECTION' }));
                    }
                  }}
                />
              </details>
            )}

            <div className="mentor-input-dock">
              <div className="voice-session-controls">
                <button className="primary voice-turn-button" aria-label={recording ? 'Done speaking' : speaking ? 'Interrupt and talk' : 'Talk to your mentor'} disabled={!workbench.sessionId || workbench.saveInFlight || workbench.editorDirty || !workbench.specAcknowledged} onClick={() => { chooseInput('voice'); void perform(microphone); }}><Icon name={recording ? 'arrow' : 'mic'} />{recording ? 'Send voice' : speaking ? 'Interrupt & talk' : 'Talk to Astra'}</button>
                <p>{recording ? 'Sends after 10 seconds of quiet. Keep talking to continue.' : speaking ? 'You can interrupt. Your words will not be discarded.' : 'Voice first. Take your time to think.'}</p>
                <button className="voice-text-toggle" aria-expanded={showTranscript} onClick={() => setShowTranscript(value => !value)}>{showTranscript ? 'Hide transcript & text' : 'Transcript & text'}</button>
              </div>
              {showTranscript && <div className="mentor-input-box">
                <textarea
                  aria-label="Editable Learner Transcript"
                  placeholder="Explain the problem and your approach in your own words..."
                  value={workbench.editableTranscript}
                  onChange={e => setWorkbench(prev => ({ ...prev, editableTranscript: e.target.value, proposedClaim: null }))}
                  onKeyDown={e => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      if (workbench.editableTranscript.trim()) void perform(proposeTranscript);
                    }
                  }}
                  rows={1}
                />
                <button
                  type="button"
                  className="mentor-send-action"
                  disabled={busy || !workbench.editableTranscript.trim()}
                  onClick={() => { void perform(proposeTranscript); }}
                  aria-label="Send explanation"
                  title="Send explanation"
                >
                  <Icon name="arrow" />
                </button>
              </div>}
              {showTranscript && !settingsOpen && <p className="mentor-dock-footer" role="status">{voiceMessage}</p>}
            </div>

            <details className="advanced-practice">
              <summary>Challenge & practice tools</summary>
              <fieldset disabled={busy || !workbench.sessionId || workbench.editorDirty || workbench.saveInFlight || !workbench.specAcknowledged}>
                <legend>Explain, predict and confirm</legend>
                <PredictionCaptureCard
                  outputKind={currentExercise?.output_schema?.kind ?? 'integer'}
                  challenge={workbench.activeChallenge}
                  predictedValue={predictedValue}
                  predictionReason={predictionReason}
                  onChangePredictedValue={setPredictedValue}
                  onChangePredictionReason={setPredictionReason}
                  onIssueDiagnosticChallenge={() => { void perform(() => issueChallenge('DIAGNOSTIC')); }}
                  onSubmitPredictionProposal={() => { void perform(proposeClaim); }}
                />
                <button type="button" onClick={() => { void perform(proposeTranscript); }}>Propose Transcript Interpretation</button>
              </fieldset>
              <div className="coach-audio-actions">
                <button disabled={busy || !shouldRequestVoice(audioPreferences) || !workbench.activeArtifact || !workbench.activeTurnId || workbench.editorDirty || workbench.diagnosticHidden} onClick={() => { void perform(playCoach); }}>Play Coach Voice</button>
                <button disabled={busy || !hasVoiceReplay || !shouldRequestVoice(audioPreferences) || workbench.editorDirty || !sameRevision(voiceReplayRevision.current, workbench.revision)} onClick={() => { void perform(replayVoice); }}>Replay last voice</button>
              </div>
              {workbench.proposedClaim && workbench.proposedClaim.claim_type !== 'OUTPUT_PREDICTION_AND_REASON' && workbench.proposedClaim.claim_type !== 'UNSUPPORTED_CLAIM' && <button type="button" disabled={busy || workbench.editorDirty} onClick={() => { void perform(confirmClaim); }}>Confirm Explanation (No Execution)</button>}
              {workbench.proposedClaim?.claim_type === 'OUTPUT_PREDICTION_AND_REASON' && <button type="button" disabled={busy || workbench.editorDirty} onClick={() => { void perform(confirmClaim); }}>Submit prediction & run</button>}
              <FreshCaseTransferCard state={workbench} isBusy={busy} onIssueTransferChallenge={() => { void perform(() => issueChallenge('TRANSFER')); }} />
            </details>
          </aside>
            );
          })()}
          <div className="results-resize"><ResizeHandle label="Resize results" orientation="horizontal" reverse value={product.resultsHeight} min={120} max={400} defaultValue={190} onChange={resultsHeight => setProduct(prev => ({ ...prev, resultsHeight }))} /></div>
          <section id="results-pane" className="results-pane" aria-label="Results workspace"><div className="results-heading"><AccessibleTabs label="Result views" controls={{ Evidence: 'evidence-panel', Session: 'session-panel' }} tabs={['Evidence', 'Session']} selected={resultPane} onSelect={setResultPane} /><div className="button-row"><button onClick={() => { void perform(cancel); }}>Cancel / Stop Audio</button><button disabled={busy || !workbench.sessionId || workbench.editorDirty || workbench.saveInFlight || !workbench.specAcknowledged || !workbench.priorFailureArtifactId} onClick={() => { void perform(verifyRepair); }}>Verify Saved Repair</button>{verification?.status === 'EXECUTION_UNAVAILABLE' && <button disabled={busy || workbench.editorDirty || workbench.saveInFlight || !workbench.activeTurnId} onClick={() => { void perform(retryExecution); }}>Retry Unavailable Execution</button>}</div></div>
            <div className="results-scroll" id={resultPane === 'Evidence' ? 'evidence-panel' : 'session-panel'} role="tabpanel" aria-labelledby={resultPane === 'Evidence' ? 'evidence-panel-tab' : 'session-panel-tab'}>{resultPane === 'Evidence' ? <><ExecutionComparisonCard artifact={workbench.editorDirty ? null : workbench.activeArtifact} isStale={workbench.editorDirty} diagnosticHidden={workbench.diagnosticHidden} verificationReport={verification} /><TraceScrubberPanel trace={trace} selectedIndex={workbench.selectedTraceStepIndex} onSelectIndex={selectedTraceStepIndex => setWorkbench(prev => ({ ...prev, selectedTraceStepIndex, activeView: 'TRACE_SCRUBBER_INSPECTION' }))} />{!verification && !trace && <div className="evidence-empty"><strong>{workbench.editorDirty ? 'Your code changed. Previous results are hidden.' : workbench.diagnosticHidden ? 'The answer stays hidden until you confirm.' : 'Nothing has run yet.'}</strong><p>{workbench.editorDirty ? 'Save a revision, then explain and check it again.' : 'Choose an input, make a prediction, and review its interpretation before execution.'}</p></div>}</> : <section aria-label="Session Summary"><h2>Practice session summary</h2><p>Code version: {workbench.revision?.code_version_id ?? 'Not saved'}. {workbench.editorDirty ? 'Previous results superseded by unsaved edits.' : `Prediction: ${workbench.activeArtifact?.prediction_status ?? 'Not revealed'}. Bounded verification: ${verification?.status ?? 'Not run'}.`}</p><p>Checkpoint completion is bounded observed evidence, never proven mastery.</p></section>}{workbench.learningState === 'PRACTICE_CHECKPOINT_COMPLETED' && <section aria-label="Practice Summary"><h2>Practice checkpoint completed</h2><p>You completed a bounded practice checkpoint. Review your prediction and code verification separately.</p></section>}</div>
          </section>
        </div>
      </>}
    </main>}
    {settingsOpen && <SettingsDialog onClose={closeSettings}>
      <section className="settings-section"><h3>Appearance &amp; layout</h3><label>Theme<select value={product.theme} onChange={e => setProduct(prev => ({ ...prev, theme: e.target.value as 'light' | 'dark' | 'system' }))}><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select></label><button onClick={() => setProduct(prev => ({ ...prev, statementWidth: DEFAULT_PRODUCT_STATE.statementWidth, coachWidth: DEFAULT_PRODUCT_STATE.coachWidth, resultsHeight: DEFAULT_PRODUCT_STATE.resultsHeight, coachCollapsed: false }))}>Reset workspace layout</button><p>Drag pane dividers or use arrow keys. Home resets a divider. On smaller screens, use the pane tabs.</p></section>
      <section className="settings-section" aria-label="Microphone Setup"><h3>Audio &amp; language</h3><p>Text comes first. Microphone permission is requested only when you choose to record.</p>
        <label className="checkbox-label always-voice-setting" style={{ padding: '9px 12px', background: 'rgba(255,115,92,0.12)', borderRadius: '10px', border: '1px solid rgba(255,115,92,0.3)', marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <input
            type="checkbox"
            checked={product.alwaysVoiceOn === true}
            onChange={e => {
              const enabled = e.target.checked;
              setProduct(prev => ({
                ...prev,
                alwaysVoiceOn: enabled,
                inputChoice: enabled ? 'voice' : prev.inputChoice,
              }));
              if (enabled) {
                void voice.current.unlockAudioFromGesture();
                updateAudio({ textOnly: false, voiceOutput: true, autoSpeak: true, introductions: true, muted: false });
              }
            }}
          />
          <span><strong>Always voice-on mode</strong> (Default to voice coach on problems without asking)</span>
        </label>
        <label className="checkbox-label"><input type="checkbox" checked={audioPreferences.textOnly} onChange={e => chooseInput(e.target.checked ? 'text' : 'voice')} />Text-only mode (no microphone or voice requests)</label><label className="checkbox-label"><input type="checkbox" checked={audioPreferences.voiceOutput} onChange={e => { if (e.target.checked) void voice.current.unlockAudioFromGesture(); updateAudio({ voiceOutput: e.target.checked }); }} />Voice output enabled</label><label className="checkbox-label"><input type="checkbox" checked={audioPreferences.autoSpeak} disabled={audioPreferences.textOnly || !audioPreferences.voiceOutput} onChange={e => updateAudio({ autoSpeak: e.target.checked })} />Automatically speak new coach replies</label><label className="checkbox-label"><input type="checkbox" checked={audioPreferences.muted} onChange={e => updateAudio({ muted: e.target.checked })} />Mute voice playback</label><label className="checkbox-label"><input type="checkbox" checked={audioPreferences.introductions} onChange={e => updateAudio({ introductions: e.target.checked })} />Problem introductions when you start a session</label><label>Voice volume<input type="range" min="0" max="1" step="0.1" value={audioPreferences.volume} onChange={e => updateAudio({ volume: Number(e.target.value) })} /></label><label>Playback speed<select value={audioPreferences.speed} onChange={e => updateAudio({ speed: Number(e.target.value) })}>{[0.75,1,1.25,1.5,2].map(speed => <option key={speed} value={speed}>{speed}×</option>)}</select></label><p role="status">{voiceMessage}</p><div className="button-row"><button disabled={busy || !workbench.sessionId || !shouldRequestVoice(audioPreferences)} onClick={() => { void perform(() => playOrientation('test-voice')); }}>Test voice</button><button disabled={busy || !workbench.sessionId || !shouldRequestVoice(audioPreferences)} onClick={() => { void perform(() => playOrientation('introduction')); }}>Play problem introduction</button><button onClick={() => { void bargeIn().catch(fail); }}>Stop audio</button></div><label>Language for next session<select value={product.language} onChange={e => setProduct(prev => ({ ...prev, language: e.target.value as 'en-IN' | 'ta-IN,en-IN' }))}><option value="en-IN">English</option><option value="ta-IN,en-IN">Tanglish</option></select></label><p>{workbench.sessionId ? `This session uses ${workbench.languageMode === 'en-IN' ? 'English' : 'Tanglish'} for recognition and playback. Language changes apply when you start a new session.` : 'Your language choice is saved for new sessions.'}</p><p>{micMessage}</p><meter aria-label="Microphone energy" min={0} max={1} value={rms} /><div className="button-row"><button onClick={() => { chooseInput('text'); setWorkbench(prev => ({ ...prev, interactionMode: 'TYPED_FALLBACK', proposedClaim: null, activeTurnId: null })); }}>Use Typed Input</button><button disabled={busy || audioPreferences.textOnly} onClick={() => { void perform(checkMicrophone); }}>Check Microphone</button></div></section>
      <details className="settings-section"><summary>Technical diagnostics</summary><p data-testid="phase-status-banner">Coordinator: {health?.status ?? 'Unavailable'} · Public custom execution: {executionReadiness}</p><label>Recognition transport<select disabled={recording || busy} value={sttTransport} onChange={e => setSttTransport(e.target.value as 'REST' | 'WS')}><option value="REST">REST (recorded turn)</option><option value="WS">WebSocket (buffered turn)</option></select></label><label>Playback<select disabled={busy} value={ttsTransport} onChange={e => setTtsTransport(e.target.value as 'STREAM' | 'WAV')}><option value="STREAM">Streaming PCM</option><option value="WAV">Complete WAV fallback</option></select></label><p>Turn #{workbench.turnGeneration} / Attempt #{workbench.captureAttemptId}. Learning state: {workbench.learningState}. View: {workbench.activeView}.</p><p>Brand status: <span data-testid="branding-status-badge">{branding.productNameStatus}</span></p><button onClick={() => setWorkbench(prev => ({ ...prev, diagnosticsOpen: !prev.diagnosticsOpen }))}>Show speech diagnostics</button><DiagnosticsDrawer state={workbench} />{presets.map(p => <p key={p.preset_id}>{p.title}: {p.provenance_label}</p>)}</details>
      <section className="settings-section"><h3>Practice data</h3><p>Drafts and bookmarks are saved on this device. Session access stays in this browser tab.</p><div className="button-row"><button disabled={!workbench.sessionId || busy || workbench.editorDirty} onClick={() => { void perform(async () => { const s = requireReady(); const epoch = generation.current; const bundle = await api.exportSessionBundle(s.sessionId); if (!isCurrent(epoch, s)) return; const url = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' })); const a = document.createElement('a'); a.href = url; a.download = 'practice-session.json'; a.click(); URL.revokeObjectURL(url); }); }}>Export JSON</button><button className="danger" disabled={!workbench.sessionId || busy} onClick={() => { void perform(deletePractice); }}>Delete Session</button></div></section>
    </SettingsDialog>}
  </div>;
}
export default App;
