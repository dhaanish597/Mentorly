import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useCodebaseVoice } from '../features/codebase/useCodebaseVoice';

const play = vi.fn();
vi.mock('../services/audioPlayer', () => ({
  AudioPlayer: class { bargeInStop = vi.fn(); playWavBytes = play; },
}));
vi.mock('../services/audioRecorder', () => ({ AudioRecorder: class {} }));

afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

it('does not play audio when stopped while the response body is downloading', async () => {
  let completeBody!: (body: ArrayBuffer) => void;
  const body = new Promise<ArrayBuffer>((resolve) => { completeBody = resolve; });
  const arrayBuffer = vi.fn(() => body);
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, arrayBuffer }));
  const { result } = renderHook(() => useCodebaseVoice({
    workspace: { id: 'w', token: 'secret' } as never,
    sessionId: 's', onTurnComplete: vi.fn(), onError: vi.fn(),
  }));
  let pending!: Promise<boolean>;
  await act(async () => {
    pending = result.current.playAudioUrl('/api/v1/codebase-learning/audio/test.wav');
    await Promise.resolve();
  });
  expect(arrayBuffer).toHaveBeenCalled();
  act(() => result.current.stopVoice());
  await act(async () => { completeBody(new ArrayBuffer(8)); expect(await pending).toBe(false); });
  expect(play).not.toHaveBeenCalled();
  expect(result.current.voiceState).toBe('IDLE');
});
