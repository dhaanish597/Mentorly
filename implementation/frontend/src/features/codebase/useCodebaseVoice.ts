import { useCallback, useEffect, useRef, useState } from 'react';
import { AudioPlayer } from '../../services/audioPlayer';
import { AudioRecorder, type AssembledWavRecording } from '../../services/audioRecorder';
import { submitVoiceTurn, type TurnResult } from './codebaseApi';
import type { Workspace } from '../../studioApi';

export type VoiceState =
  | 'INITIALIZING'
  | 'SPEAKING'
  | 'LISTENING'
  | 'PROCESSING'
  | 'IDLE'
  | 'PERMISSION_REQUIRED'
  | 'ERROR';

export type UseCodebaseVoiceOptions = {
  workspace: Workspace;
  sessionId: string;
  initialAudioUrl?: string | null;
  onTurnComplete: (result: TurnResult) => void;
  onError: (errorMsg: string) => void;
  enabled?: boolean;
};

export function useCodebaseVoice({
  workspace,
  sessionId,
  initialAudioUrl,
  onTurnComplete,
  onError,
  enabled = true,
}: UseCodebaseVoiceOptions) {
  const [voiceState, setVoiceState] = useState<VoiceState>('INITIALIZING');
  const [liveTranscript, setLiveTranscript] = useState('');
  const [audioUnlocked, setAudioUnlocked] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [activeAudioUrl, setActiveAudioUrl] = useState<string | null>(null);

  const playerRef = useRef<AudioPlayer | null>(null);
  const audioElementRef = useRef<HTMLAudioElement | null>(null);
  const recorderRef = useRef<AudioRecorder | null>(null);
  const isMounted = useRef(true);
  const generation = useRef(0);
  const currentVoiceState = useRef<VoiceState>('INITIALIZING');

  const setSafeState = useCallback((state: VoiceState) => {
    currentVoiceState.current = state;
    if (isMounted.current) {
      setVoiceState(state);
    }
  }, []);

  useEffect(() => {
    isMounted.current = true;
    const activeGeneration = generation;
    playerRef.current = new AudioPlayer();
    return () => {
      isMounted.current = false;
      activeGeneration.current++;
      if (audioElementRef.current) {
        try {
          audioElementRef.current.pause();
          audioElementRef.current.src = '';
        } catch {
          // ignore
        }
        audioElementRef.current = null;
      }
      playerRef.current?.bargeInStop();
      if (recorderRef.current) {
        try {
          void Promise.resolve(recorderRef.current.dispose()).catch(() => {});
        } catch {
          // ignore
        }
        recorderRef.current = null;
      }
    };
  }, []);

  // Stop current voice loop, audio playback, and recording
  const stopVoice = useCallback(() => {
    generation.current++;
    if (audioElementRef.current) {
      try {
        audioElementRef.current.pause();
        audioElementRef.current.currentTime = 0;
      } catch {
        // ignore
      }
      audioElementRef.current = null;
    }
    setActiveAudioUrl(null);
    playerRef.current?.bargeInStop();
    if (recorderRef.current) {
      recorderRef.current.dispose().catch(() => {});
      recorderRef.current = null;
    }
    setIsRecording(false);
    setSafeState('IDLE');
  }, [setSafeState]);

  // Stop recording and submit to voice turn API (can be called by VAD or manually)
  const stopAndSubmit = useCallback(
    async (expectedGen?: number) => {
      const recorder = recorderRef.current;
      if (!recorder) {
        setIsRecording(false);
        setSafeState('IDLE');
        return;
      }
      if (expectedGen !== undefined && expectedGen !== generation.current) return;
      recorderRef.current = null;
      setIsRecording(false);
      setSafeState('PROCESSING');

      try {
        const recording: AssembledWavRecording = await recorder.stopMicrophoneCapture();
        if (expectedGen !== undefined && expectedGen !== generation.current) return;

        // Verify audio was captured and has reasonable length
        if (recording.wavBytes.byteLength < 400 || recording.durationSec < 0.3) {
          // No speech or too short, resume listening
          void startListening();
          return;
        }

        const result = await submitVoiceTurn(workspace, sessionId, recording.wavBytes);
        if (expectedGen !== undefined && expectedGen !== generation.current) return;

        onTurnComplete(result);

        // If mentor returned audio, play it automatically!
        if (result.mentor_message.audio_url && enabled) {
          void playAudioUrl(result.mentor_message.audio_url);
        } else {
          void startListening();
        }
      } catch (err) {
        if (expectedGen === undefined || expectedGen === generation.current) {
          onError(err instanceof Error ? err.message : 'Speech recognition failed.');
          setSafeState('IDLE');
        }
      } finally {
        await recorder.dispose().catch(() => {});
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [enabled, onTurnComplete, onError, sessionId, setSafeState, workspace]
  );

  // Start microphone capture helper
  const startListening = useCallback(async () => {
    if (!isMounted.current || !enabled) return;
    const localGen = ++generation.current;

    // Stop mentor audio if playing
    if (audioElementRef.current) {
      try {
        audioElementRef.current.pause();
        audioElementRef.current.currentTime = 0;
      } catch {
        // ignore
      }
      audioElementRef.current = null;
    }
    setActiveAudioUrl(null);
    playerRef.current?.bargeInStop();

    setSafeState('LISTENING');
    setIsRecording(true);
    setLiveTranscript('');

    try {
      const recorder = new AudioRecorder(sessionId, 1);
      recorderRef.current = recorder;

      await recorder.startMicrophoneCapture({
        silenceMs: 2500, // 2.5s silence threshold for end-of-utterance
        onSilenceTimeout: () => {
          // Finished speaking! Stop recorder and submit automatically
          if (localGen === generation.current && recorderRef.current) {
            void stopAndSubmit(localGen);
          }
        },
        onDeviceLost: (reason: string) => {
          onError(`Microphone disconnected: ${reason}`);
          setSafeState('ERROR');
          setIsRecording(false);
        },
      });
    } catch {
      if (localGen === generation.current) {
        onError('Microphone permission required for voice mentoring. Use text or allow microphone.');
        setSafeState('PERMISSION_REQUIRED');
        setIsRecording(false);
      }
    }
  }, [enabled, onError, sessionId, setSafeState, stopAndSubmit]);

  // Play audio url helper (guaranteed transitions: SPEAKING -> LISTENING)
  const playAudioUrl = useCallback(
    async (audioUrl: string): Promise<boolean> => {
      if (!audioUrl || !isMounted.current || !enabled) {
        return false;
      }

      // Stop any existing playback
      if (audioElementRef.current) {
        try {
          audioElementRef.current.pause();
          audioElementRef.current.currentTime = 0;
        } catch {
          // ignore
        }
        audioElementRef.current = null;
      }
      playerRef.current?.bargeInStop();

      setSafeState('SPEAKING');
      setActiveAudioUrl(audioUrl);
      const currentGen = generation.current;

      // Audio is private to the workspace and must be fetched with its capability.
      try {
        if (!/^\/api\/v1\/codebase-learning\/audio\/[A-Za-z0-9_]+\.wav$/.test(audioUrl)) throw new Error('Invalid audio URL.');
        const resp = await fetch(audioUrl, { headers: { 'X-Workspace-Id': workspace.id, 'X-Workspace-Token': workspace.token } });
        if (!isMounted.current || currentGen !== generation.current) return false;
        if (!resp.ok) {
          throw new Error('Could not fetch synthesized speech.');
        }
        const arrayBuf = await resp.arrayBuffer();
        if (!isMounted.current || currentGen !== generation.current) return false;
        const wavBytes = new Uint8Array(arrayBuf);

        return await new Promise<boolean>((resolve) => {
          playerRef.current?.playWavBytes({
            wavBytes,
            sessionId,
            turnId: `turn_${Date.now()}`,
            turnGeneration: 1,
            onEnded: () => {
              setActiveAudioUrl(null);
              if (isMounted.current && currentGen === generation.current && enabled) {
                setSafeState('LISTENING');
                void startListening();
                resolve(true);
              } else {
                setSafeState('IDLE');
                resolve(false);
              }
            },
            onAutoplayBlocked: () => {
              setActiveAudioUrl(null);
              setSafeState('PERMISSION_REQUIRED');
              resolve(false);
            },
          }).then((res) => {
            if (!res.started) {
              setActiveAudioUrl(null);
              setSafeState('PERMISSION_REQUIRED');
              resolve(false);
            }
          }).catch((err) => {
            setActiveAudioUrl(null);
            onError(err instanceof Error ? err.message : 'Audio playback failed');
            setSafeState('IDLE');
            resolve(false);
          });
        });
      } catch (err) {
        setActiveAudioUrl(null);
        onError(err instanceof Error ? err.message : 'Audio download failed');
        setSafeState('IDLE');
        return false;
      }
    },
    [enabled, onError, sessionId, setSafeState, startListening, workspace.id, workspace.token]
  );

  // Initial unlock & greeting trigger
  const initializeVoice = useCallback(async () => {
    setAudioUnlocked(true);
    if (initialAudioUrl) {
      const played = await playAudioUrl(initialAudioUrl);
      if (!played && isMounted.current) {
        void startListening();
      }
    } else {
      void startListening();
    }
  }, [initialAudioUrl, playAudioUrl, startListening]);

  return {
    voiceState,
    isRecording,
    activeAudioUrl,
    liveTranscript,
    audioUnlocked,
    initializeVoice,
    startListening,
    stopAndSubmit,
    stopVoice,
    playAudioUrl,
  };
}
