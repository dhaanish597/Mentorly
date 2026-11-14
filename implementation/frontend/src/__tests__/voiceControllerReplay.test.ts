import { afterEach, describe, expect, it, vi } from 'vitest';
import { AudioPlayer, type PlayWavBytesParams } from '../services/audioPlayer';
import { VoiceController } from '../voice/controller';
import { DEFAULT_AUDIO_PREFERENCES } from '../voice/preferences';
import { encodePcm16ToWavBytes } from '../services/audioRecorder';

const params: PlayWavBytesParams = { sessionId: 'private-session', turnId: 'turn', turnGeneration: 1, wavBytes: new Uint8Array([1, 2, 3]) };
afterEach(() => vi.restoreAllMocks());
function setup() {
  const player = new AudioPlayer();
  const play = vi.spyOn(player, 'playWavBytes').mockResolvedValue({ started: true, fallbackAck: null });
  return { player, play, voice: new VoiceController(player) };
}
describe('message-keyed private voice replay', () => {
  it('bounds entry count and prunes obsolete artifact contexts without losing current hints or last replay', async () => {
    const { voice, play } = setup();
    for (let index = 0; index < 15; index++) await voice.play(params, undefined, `message-${index}`, 'artifact-a/full-revision');
    expect(voice.hasReplay('message-0')).toBe(false);
    expect(Array.from({ length: 15 }, (_, index) => voice.hasReplay(`message-${index}`)).filter(Boolean)).toHaveLength(12);
    for (const level of [1, 2, 3]) await voice.play(params, undefined, `hint-${level}`, 'artifact-b/full-revision');
    expect(voice.hasReplay('message-14')).toBe(false);
    for (const level of [1, 2, 3]) expect(voice.hasReplay(`hint-${level}`)).toBe(true);
    await voice.play({ ...params, turnId: 'orientation' });
    await voice.replay(); expect(play.mock.lastCall?.[0].turnId).toBe('orientation');
    for (const level of [1, 2, 3]) expect(voice.hasReplay(`hint-${level}`)).toBe(true);
  });
  it('caps retained audio bytes and does not retain an oversized single playback', async () => {
    const { voice, play } = setup();
    for (let index = 0; index < 10; index++) await voice.play({ ...params, wavBytes: new Uint8Array(1024 * 1024) }, undefined, `large-${index}`, 'current');
    expect(Array.from({ length: 10 }, (_, index) => voice.hasReplay(`large-${index}`)).filter(Boolean)).toHaveLength(8);
    expect(voice.hasReplay('large-0')).toBe(false);
    await voice.play({ ...params, wavBytes: new Uint8Array(8 * 1024 * 1024 + 1) }, undefined, 'oversized', 'current');
    expect(voice.hasReplay('oversized')).toBe(false);
    await voice.play({ ...params, wavBytes: new Uint8Array(8 * 1024 * 1024 + 1) }, undefined, 'large-9', 'current');
    expect(voice.hasReplay('large-9')).toBe(false);
    const count = play.mock.calls.length;
    expect((await voice.replay()).started).toBe(false); expect(play).toHaveBeenCalledTimes(count);
  });
  it('prunes all obsolete full revisions even if the message key is unchanged', async () => {
    const { voice } = setup();
    const revision = { session_id: params.sessionId, exercise_id: 'ex1_shortest_subarray' as const, spec_version: 'v1_positive_only' as const, code_version_id: 1, code_hash: 'hash', turn_generation: 1 };
    await voice.play({ ...params, revision }, undefined, 'old');
    await voice.play({ ...params, revision: { ...revision, turn_generation: 2 } }, undefined, 'new');
    expect(voice.hasReplay('old')).toBe(false); expect(voice.hasReplay('new')).toBe(true);
    await voice.play({ ...params, revision: { ...revision, code_hash: 'next-hash' }, turnId: 'new-orientation' });
    expect(voice.hasReplay('new')).toBe(false);
  });
  it('does not evict a newer replacement or restore bytes after a stale failure and clear', async () => {
    const { voice, play } = setup();
    let reject!: (error: Error) => void;
    play.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }));
    const pending = voice.play(params, undefined, 'same', 'context');
    const failure = expect(pending).rejects.toThrow('old decode');
    await voice.play({ ...params, wavBytes: new Uint8Array([8]) }, undefined, 'same', 'context');
    reject(new Error('old decode')); await failure;
    expect(voice.hasReplay('same')).toBe(true);
    await voice.replay(undefined, 'same'); expect(play.mock.lastCall?.[0].wavBytes).toEqual(new Uint8Array([8]));
    play.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }));
    const clearing = voice.play(params, undefined, 'cleared', 'context');
    const clearingFailure = expect(clearing).rejects.toThrow('cleared decode');
    voice.clearReplay(); reject(new Error('cleared decode')); await clearingFailure;
    expect(voice.hasReplay('cleared')).toBe(false); expect((await voice.replay()).started).toBe(false);
  });
  it('evicts poisoned keyed and last replay after a replay throws while preserving valid siblings', async () => {
    const { voice, play } = setup();
    await voice.play(params, undefined, 'valid'); await voice.play(params, undefined, 'bad');
    play.mockRejectedValueOnce(new Error('source failed'));
    await expect(voice.replay()).rejects.toThrow('source failed');
    expect(voice.hasReplay('bad')).toBe(false); expect(voice.hasReplay('valid')).toBe(true);
    expect((await voice.replay()).started).toBe(false);
  });
  it('retains current hints through mute and replays only after voice is restored', async () => {
    const { voice, play } = setup();
    await voice.play(params, undefined, 'current');
    voice.setPreferences({ ...DEFAULT_AUDIO_PREFERENCES, muted: true });
    expect((await voice.replay(undefined, 'current')).started).toBe(false); expect(play).toHaveBeenCalledOnce();
    expect(voice.hasReplay('current')).toBe(true);
    voice.setPreferences(DEFAULT_AUDIO_PREFERENCES);
    expect((await voice.replay(undefined, 'current')).started).toBe(true); expect(play).toHaveBeenCalledTimes(2);
  });
  it('runs the real WAV player through completion, interruption, preferences, and private replay cleanup', async () => {
    const nodes: Array<{ onended: (() => void) | null; playbackRate: { value: number }; connect: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn>; start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn>; buffer: AudioBuffer | null }> = [];
    const gain = { gain: { value: 1 }, connect: vi.fn(), disconnect: vi.fn() };
    const context = { state: 'running', destination: {}, createGain: () => gain, close: vi.fn().mockResolvedValue(undefined), createBuffer: (_channels: number, frames: number) => ({ getChannelData: () => new Float32Array(frames) }), createBufferSource: () => {
      const node = { onended: null as (() => void) | null, playbackRate: { value: 1 }, buffer: null as AudioBuffer | null, connect: vi.fn(), disconnect: vi.fn(), start: vi.fn(), stop: vi.fn() }; nodes.push(node); return node;
    } } as unknown as AudioContext;
    const player = new AudioPlayer(); const voice = new VoiceController(player);
    const ended = vi.fn();
    const wavBytes = encodePcm16ToWavBytes(new Int16Array([100, -100, 300]), 16000);
    const p = { ...params, wavBytes, playbackId: 'original', audioContextFactory: () => context, onEnded: ended };
    expect((await voice.play(p, undefined, 'one')).started).toBe(true);
    voice.setPreferences({ ...DEFAULT_AUDIO_PREFERENCES, volume: 0.4, speed: 1.5 });
    expect(gain.gain.value).toBe(0.4); expect(nodes[0].playbackRate.value).toBe(1.5);
    nodes[0].onended?.();
    expect(ended).toHaveBeenCalledWith(expect.objectContaining({ playback_status: 'COMPLETED', playback_id: 'original' }));
    expect(player.isPlaying).toBe(false);
    await voice.replay(undefined, 'one');
    nodes[1].onended?.();
    expect(ended).toHaveBeenCalledOnce();
    await voice.replay(undefined, 'one');
    const stopped = voice.bargeInStop();
    expect(stopped.ack?.playback_status).toBe('INTERRUPTED');
    expect(nodes[2].stop).toHaveBeenCalledOnce();
    await voice.dispose();
    expect(context.close).toHaveBeenCalledOnce();
    expect(gain.disconnect).toHaveBeenCalledOnce();
    expect(voice.hasReplay('one')).toBe(false);
  });
  it('keeps real autoplay failures replayable and rejects unsupported audio graphs', async () => {
    const bytes = encodePcm16ToWavBytes(new Int16Array([1, -1]), 16000);
    const blocked = vi.fn();
    const context = { state: 'suspended', resume: vi.fn().mockRejectedValue(new Error('gesture required')), close: vi.fn().mockResolvedValue(undefined) } as unknown as AudioContext;
    const voice = new VoiceController();
    expect((await voice.play({ ...params, wavBytes: bytes, audioContextFactory: () => context, onAutoplayBlocked: blocked }, undefined, 'blocked')).started).toBe(false);
    expect(blocked).toHaveBeenCalledOnce(); expect(voice.hasReplay('blocked')).toBe(true);
    await voice.dispose();
    const unsupported = new VoiceController();
    await expect(unsupported.play({ ...params, wavBytes: bytes, audioContextFactory: () => ({ state: 'running' } as AudioContext) }, undefined, 'bad')).rejects.toThrow('neither createBuffer nor decodeAudioData');
    await unsupported.dispose();
  });
  it('replays each message independently while preserving last replay', async () => {
    const { play, voice } = setup();
    await voice.play(params, undefined, 'artifact/revision/1');
    await voice.play({ ...params, wavBytes: new Uint8Array([4, 5]) }, undefined, 'artifact/revision/2');
    expect(voice.hasReplay('artifact/revision/1')).toBe(true);
    await voice.replay(undefined, 'artifact/revision/1');
    expect(play.mock.calls[2][0].wavBytes).toEqual(new Uint8Array([1, 2, 3]));
    await voice.replay();
    expect(play.mock.calls[3][0].wavBytes).toEqual(new Uint8Array([1, 2, 3]));
    expect(await voice.replay(undefined, 'another-revision/1')).toEqual({ started: false, fallbackAck: null });
    expect(play).toHaveBeenCalledTimes(4);
  });
  it('owns an immutable copy of caller bytes and revision', async () => {
    const { play, voice } = setup();
    const bytes = new Uint8Array([1, 2]);
    await voice.play({ ...params, wavBytes: bytes }, undefined, 'one');
    bytes[0] = 99;
    await voice.replay(undefined, 'one');
    expect(play.mock.calls[1][0].wavBytes).toEqual(new Uint8Array([1, 2]));
  });
  it.each([{ muted: true }, { textOnly: true }, { volume: 0 }, { voiceOutput: false }])('does not play or cache while voice is off %j', async patch => {
    const { play, voice } = setup();
    voice.setPreferences({ ...DEFAULT_AUDIO_PREFERENCES, ...patch });
    expect((await voice.play(params, undefined, 'one')).started).toBe(false);
    expect(voice.hasReplay('one')).toBe(false);
    expect(play).not.toHaveBeenCalled();
  });
  it('clears every private message on clear and disposal', async () => {
    const { voice } = setup();
    await voice.play(params, undefined, 'one');
    await voice.play(params, undefined, 'two');
    voice.clearReplay();
    expect(voice.hasReplay('one')).toBe(false);
    expect(voice.hasReplay('two')).toBe(false);
    expect((await voice.replay()).started).toBe(false);
    await voice.play(params, undefined, 'three');
    await voice.dispose();
    expect(voice.hasReplay('three')).toBe(false);
    expect((await voice.play(params, undefined, 'four')).started).toBe(false);
  });
  it('rejects pre-aborted playback without caching and cleans error listeners', async () => {
    const { player, play, voice } = setup();
    const abort = new AbortController(); abort.abort();
    await expect(voice.play(params, abort.signal, 'one')).rejects.toMatchObject({ name: 'AbortError' });
    expect(voice.hasReplay('one')).toBe(false);
    play.mockRejectedValueOnce(new Error('decode failed'));
    const request = new AbortController();
    await expect(voice.play(params, request.signal, 'two')).rejects.toThrow('decode failed');
    expect(voice.hasReplay('two')).toBe(false);
    expect((await voice.replay()).started).toBe(false);
    const stop = vi.spyOn(player, 'bargeInStop'); stop.mockClear();
    request.abort();
    expect(stop).not.toHaveBeenCalled();
  });
  it('keeps blocked audio available for a later gesture without a provider', async () => {
    const { play, voice } = setup();
    play.mockImplementationOnce(async p => {
      const ack = AudioPlayer.buildReadTextFallbackAck(p.sessionId, p.turnId, p.turnGeneration);
      p.onAutoplayBlocked?.(ack);
      return { started: false, fallbackAck: ack };
    });
    const blocked = vi.fn();
    expect((await voice.play({ ...params, onAutoplayBlocked: blocked }, undefined, 'one')).started).toBe(false);
    expect(blocked).toHaveBeenCalledOnce();
    expect(voice.hasReplay('one')).toBe(true);
    expect((await voice.replay(undefined, 'one')).started).toBe(true);
  });
});
