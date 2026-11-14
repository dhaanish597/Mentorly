import { afterEach, describe, expect, it, vi } from 'vitest';
import { SPEECH_LANGUAGES, TTS_VOICES, isSpeechLocale, resolveLanguageMode, resolveSpeechSelection, fetchSpeechCapabilities } from '../voice/languages';
import { DEFAULT_SPEECH_PREFERENCES, loadSpeechPreferences, updateSpeechPreferences, saveSpeechPreferences, subscribeSpeechPreferences, DEFAULT_AUDIO_PREFERENCES, saveAudioPreferences, subscribeAudioPreferences } from '../voice/preferences';
import { PcmFrameWriter } from '../services/speechStreaming';

afterEach(() => { localStorage.clear(); vi.unstubAllGlobals(); });

describe('product voice languages and local independent selection', () => {
  it('exposes audited locales and multilingual voices without claiming live readiness', () => {
    expect(SPEECH_LANGUAGES.map(item => item.code)).toEqual(['en-IN','hi-IN','ta-IN','te-IN','kn-IN','ml-IN','bn-IN','gu-IN','mr-IN','pa-IN']);
    expect(TTS_VOICES).toHaveLength(13);
    expect(isSpeechLocale('te-IN,en-IN')).toBe(false);
    expect(resolveLanguageMode('bn-IN', true)).toBe('bn-IN,en-IN');
    expect(resolveLanguageMode('hi-IN', true)).toBe('hi-IN,en-IN');
    expect(() => resolveLanguageMode('te-IN', true)).toThrow();
    expect(resolveSpeechSelection({sttLanguage:'hi-IN', spokenLanguage:'bn-IN', codeMixing:true, voice:'Shivani'})).toMatchObject({language_mode:'hi-IN,en-IN', language:'bn-IN', voice:'Shivani', model:'timbre-v3.0'});
  });
  it('preserves legacy audio defaults and keeps interface, STT and spoken language independent', () => {
    expect(DEFAULT_AUDIO_PREFERENCES.volume).toBe(1);
    const changed = updateSpeechPreferences(DEFAULT_SPEECH_PREFERENCES, {interfaceLanguage:'ta-IN', sttLanguage:'hi-IN', spokenLanguage:'bn-IN', voice:'Shivani', codeMixing:true});
    expect(changed.interfaceLanguage).toBe('ta-IN');
    expect(changed.sttLanguage).toBe('hi-IN');
    expect(changed.spokenLanguage).toBe('bn-IN');
    expect(DEFAULT_SPEECH_PREFERENCES.sttLanguage).toBe('en-IN');
    expect(saveSpeechPreferences(changed)).toBe(true);
    expect(loadSpeechPreferences()).toEqual(changed);
    expect(loadSpeechPreferences({getItem:()=>'{bad'})).toEqual(DEFAULT_SPEECH_PREFERENCES);
    expect(loadSpeechPreferences({getItem:()=>' {"voice":"unknown","sttLanguage":"made-up"}'})).toEqual(DEFAULT_SPEECH_PREFERENCES);
  });
  it('normalizes unsupported mixing without inventing locale pairs', () => {
    expect(updateSpeechPreferences(DEFAULT_SPEECH_PREFERENCES, {sttLanguage:'te-IN',codeMixing:true}).codeMixing).toBe(false);
  });
  it('subscribes immediately, synchronously on save, and across tabs then cleans up', () => {
    const callback=vi.fn();
    const unsubscribe=subscribeSpeechPreferences(callback);
    expect(callback).toHaveBeenLastCalledWith(DEFAULT_SPEECH_PREFERENCES);
    saveSpeechPreferences({...DEFAULT_SPEECH_PREFERENCES,voice:'Shivani'});
    expect(callback).toHaveBeenLastCalledWith(expect.objectContaining({voice:'Shivani'}));
    window.dispatchEvent(new StorageEvent('storage',{key:'viva.speech-preferences.v1',newValue:JSON.stringify({...DEFAULT_SPEECH_PREFERENCES,voice:'Harshad'})}));
    expect(callback).toHaveBeenLastCalledWith(expect.objectContaining({voice:'Harshad'}));
    unsubscribe(); const count=callback.mock.calls.length;
    saveSpeechPreferences(DEFAULT_SPEECH_PREFERENCES);
    expect(callback).toHaveBeenCalledTimes(count);
  });
  it('subscribes audio changes immediately and reports storage denial', () => {
    const callback=vi.fn(); const unsubscribe=subscribeAudioPreferences(callback);
    expect(callback).toHaveBeenCalledOnce();
    saveAudioPreferences({...DEFAULT_AUDIO_PREFERENCES,muted:true});
    expect(callback).toHaveBeenLastCalledWith(expect.objectContaining({muted:true}));
    unsubscribe();
    expect(saveSpeechPreferences(DEFAULT_SPEECH_PREFERENCES,{setItem:()=>{throw new Error('denied');}})).toBe(false);
  });
  it('fetches only backend capability info and rejects malformed replies', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok:true,json:async()=>({languages:[],voices:[]})}));
    await expect(fetchSpeechCapabilities()).rejects.toThrow();
    expect(fetch).toHaveBeenCalledWith('/api/v1/speech/capabilities',expect.objectContaining({signal:undefined}));
  });
});

describe('product voice physical thirty second frame boundary', () => {
  it('never pads beyond thirty seconds of physical PCM', () => {
    const frames:Uint8Array[]=[]; const writer=new PcmFrameWriter(frame=>frames.push(frame));
    writer.push(new Int16Array(480000)); writer.finish();
    expect(frames.reduce((sum,frame)=>sum+frame.length,0)).toBe(960000);
    expect(frames.at(-1)?.length).toBe(512);
    expect(()=>writer.push(new Int16Array(1))).toThrow();
  });
});
