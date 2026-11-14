import { describe, expect, it, vi } from 'vitest';
import { DEFAULT_AUDIO_PREFERENCES, loadAudioPreferences, saveAudioPreferences, updateAudioPreferences, shouldPlayIntroduction, shouldRequestVoice } from '../voice/preferences';
import { VoiceController } from '../voice/controller';
import { AudioPlayer } from '../services/audioPlayer';

const params = { sessionId: 'session', turnId: 'intro', turnGeneration: 0, wavBytes: new Uint8Array(44) };

describe('private audio preferences and lifecycle', () => {
  it('defaults to silent browsing and validates persisted values', () => {
    expect(DEFAULT_AUDIO_PREFERENCES.introductions).toBe(false);
    expect(shouldPlayIntroduction(DEFAULT_AUDIO_PREFERENCES)).toBe(false);
    expect(loadAudioPreferences({ getItem: () => '{bad' })).toEqual(DEFAULT_AUDIO_PREFERENCES);
    expect(loadAudioPreferences({ getItem: () => '{"volume":99,"speed":0,"muted":"true"}' })).toEqual(DEFAULT_AUDIO_PREFERENCES);
    const changed=updateAudioPreferences(DEFAULT_AUDIO_PREFERENCES,{volume:.25,speed:1.5,introductions:true});
    expect(DEFAULT_AUDIO_PREFERENCES.volume).toBe(1);
    expect(shouldPlayIntroduction(changed)).toBe(true);
    expect(shouldRequestVoice({...changed,textOnly:true})).toBe(false);
    expect(shouldPlayIntroduction({...changed,muted:true})).toBe(false);
  });
  it('separates automatic replies, voice output and mute preferences', () => {
    expect(DEFAULT_AUDIO_PREFERENCES.autoSpeak).toBe(false);
    expect(DEFAULT_AUDIO_PREFERENCES.voiceOutput).toBe(true);
    expect(loadAudioPreferences({ getItem: () => '{"volume":0.4}' }).autoSpeak).toBe(false);
    expect(shouldRequestVoice({...DEFAULT_AUDIO_PREFERENCES,voiceOutput:false})).toBe(false);
    const automatic=updateAudioPreferences(DEFAULT_AUDIO_PREFERENCES,{autoSpeak:true});
    expect(automatic.muted).toBe(false);
    expect(automatic.voiceOutput).toBe(true);
  });
  it('activates the existing playback context synchronously from a gesture', async () => {
    const rawContext={state:'suspended',resume:vi.fn(),close:vi.fn().mockResolvedValue(undefined)};
    const resume=rawContext.resume.mockImplementation(() => { rawContext.state='running'; return Promise.resolve(); });
    const context=rawContext as unknown as AudioContext;
    const factory=vi.fn(()=>context);
    const player=new AudioPlayer();
    const controller=new VoiceController(player);
    const activation=controller.unlockAudioFromGesture(factory);
    expect(factory).toHaveBeenCalledOnce();
    expect(resume).toHaveBeenCalledOnce();
    await expect(activation).resolves.toBe(true);
    await controller.dispose();
    await expect(controller.unlockAudioFromGesture(factory)).resolves.toBe(false);
    expect(factory).toHaveBeenCalledOnce();
  });
  it('persists preferences only and handles unavailable storage', () => {
    const setItem=vi.fn();
    expect(saveAudioPreferences({...DEFAULT_AUDIO_PREFERENCES,volume:.4},{setItem})).toBe(true);
    expect(setItem.mock.calls[0][1]).not.toContain('wav');
    expect(loadAudioPreferences({getItem:()=>{throw new Error('blocked');}})).toEqual(DEFAULT_AUDIO_PREFERENCES);
    expect(saveAudioPreferences(DEFAULT_AUDIO_PREFERENCES,{setItem:()=>{throw new Error('blocked');}})).toBe(false);
  });
  it('stops playback on mute, supports explicit replay and cancels pending work', async () => {
    const player=new AudioPlayer();
    const play=vi.spyOn(player,'playWavBytes').mockResolvedValue({started:true,fallbackAck:null});
    const stop=vi.spyOn(player,'bargeInStop');
    const controller=new VoiceController(player);
    controller.setPreferences({...DEFAULT_AUDIO_PREFERENCES,textOnly:true});
    expect((await controller.play(params)).started).toBe(false);
    expect(play).not.toHaveBeenCalled();
    controller.setPreferences(DEFAULT_AUDIO_PREFERENCES);
    const abort=new AbortController();
    await controller.play(params,abort.signal);
    abort.abort();
    expect(stop).toHaveBeenCalled();
    await controller.replay();
    expect(play).toHaveBeenCalledTimes(2);
    await controller.dispose();
    expect((await controller.replay()).started).toBe(false);
  });
});
