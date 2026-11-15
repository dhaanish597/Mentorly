import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { StudioVoice } from '../StudioVoice';
import { DEFAULT_AUDIO_PREFERENCES, DEFAULT_SPEECH_PREFERENCES, saveAudioPreferences, saveSpeechPreferences } from '../voice/preferences';

const recorder=vi.hoisted(()=>({start:vi.fn(),stop:vi.fn(),dispose:vi.fn()}));
vi.mock('../services/audioRecorder',()=>({AudioRecorder:class {startMicrophoneCapture=recorder.start;stopMicrophoneCapture=recorder.stop;dispose=recorder.dispose;}}));
const session={id:'studio',token:'capability',workspace:{id:'work',token:'workspace-capability'}};
const coach=(sequence=1)=>({sequence,type:'coach.action',payload:{epoch:1,text:'Explain the tradeoff.'}});
const json=(body:unknown)=>new Response(JSON.stringify(body),{status:200});
let fetcher:ReturnType<typeof vi.fn>;
let play:ReturnType<typeof vi.spyOn>;
let pause:ReturnType<typeof vi.spyOn>;
let createUrl:ReturnType<typeof vi.fn<(obj:Blob|MediaSource)=>string>>;
let revokeUrl:ReturnType<typeof vi.fn<(url:string)=>void>>;
beforeEach(()=>{
  localStorage.clear(); recorder.start.mockResolvedValue(undefined); recorder.stop.mockResolvedValue({wavBytes:new Uint8Array([1,2])}); recorder.dispose.mockResolvedValue(undefined);
  fetcher=vi.fn().mockImplementation(()=>Promise.resolve(json({epoch:1,audio_base64:'AQI=',normalized_transcript:'review me'})));vi.stubGlobal('fetch',fetcher);
  let index=0;createUrl=vi.fn<(obj:Blob|MediaSource)=>string>(()=>`blob:voice-${++index}`);revokeUrl=vi.fn<(url:string)=>void>();vi.stubGlobal('URL',class extends URL {static createObjectURL=createUrl;static revokeObjectURL=revokeUrl;});
  play=vi.spyOn(HTMLMediaElement.prototype,'play').mockResolvedValue(undefined);
  pause=vi.spyOn(HTMLMediaElement.prototype,'pause').mockImplementation(()=>undefined);
});
afterEach(()=>{cleanup();localStorage.clear();vi.restoreAllMocks();vi.resetAllMocks();vi.unstubAllGlobals();});
const mount=()=>render(<StudioVoice session={session} epoch={1} events={[coach()]} onTranscript={vi.fn()} />);
async function speak(){fireEvent.click(screen.getByRole('button',{name:'Enable coach speech'}));await waitFor(()=>expect(play).toHaveBeenCalled());}

describe('shared product studio voice preferences',()=>{
  it('uses independent STT codemix and spoken language with declared voice',async()=>{
    saveSpeechPreferences({...DEFAULT_SPEECH_PREFERENCES,sttLanguage:'hi-IN',codeMixing:true,spokenLanguage:'bn-IN',voice:'Shivani'});
    mount();fireEvent.click(screen.getByRole('button',{name:'Enable voice and talk'}));
    await screen.findByRole('button',{name:'Stop and transcribe'});fireEvent.click(screen.getByRole('button',{name:'Stop and transcribe'}));
    await screen.findByRole('button',{name:'Talk'});
    expect(JSON.parse(fetcher.mock.calls[0][1].body).language_mode).toBe('hi-IN,en-IN');
    await speak();
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toMatchObject({language:'bn-IN',voice:'Shivani'});
  });
  it('honors volume and local speed then stops on mute and text-only without extra provider calls',async()=>{
    saveAudioPreferences({...DEFAULT_AUDIO_PREFERENCES,volume:.4,speed:1.5});const view=mount();await speak();
    const audio=view.container.querySelector('audio')!;expect(audio.volume).toBe(.4);expect(audio.playbackRate).toBe(1.5);
    act(()=>{saveAudioPreferences({...DEFAULT_AUDIO_PREFERENCES,muted:true});});
    expect(pause).toHaveBeenCalled();expect(screen.getByRole('status').textContent).not.toMatch(/^Speaking\./);
    expect((screen.getByRole('button',{name:/coach/}) as HTMLButtonElement).disabled).toBe(true);
    expect(fetcher).toHaveBeenCalledOnce();
  });
  it('text-only mode never captures audio or calls a provider even with explicit button clicks',()=>{
    saveAudioPreferences({...DEFAULT_AUDIO_PREFERENCES,textOnly:true});mount();
    const talk=screen.getByRole('button',{name:'Enable voice and talk'});const coachButton=screen.getByRole('button',{name:'Enable coach speech'});
    fireEvent.click(talk);fireEvent.click(coachButton);
    expect(fetcher).not.toHaveBeenCalled();expect(recorder.start).not.toHaveBeenCalled();expect(play).not.toHaveBeenCalled();
  });
  it('cancels an in-flight response when speech language changes across tabs',async()=>{
    let resolve!:(response:Response)=>void;fetcher.mockReturnValue(new Promise<Response>(done=>{resolve=done;}));mount();
    fireEvent.click(screen.getByRole('button',{name:'Enable coach speech'}));await waitFor(()=>expect(fetcher).toHaveBeenCalled());
    act(()=>{window.dispatchEvent(new StorageEvent('storage',{key:'viva.speech-preferences.v1',newValue:JSON.stringify({...DEFAULT_SPEECH_PREFERENCES,voice:'Harshad'})}));});
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
    await act(async()=>resolve(json({epoch:1,audio_base64:'AQI='})));
    expect(play).not.toHaveBeenCalled();expect(createUrl).not.toHaveBeenCalled();
  });
  it('reports actual playback only after media play starts and resets on end',async()=>{
    let begin!:(value:void)=>void;play.mockReturnValueOnce(new Promise<void>(done=>{begin=done;}));
    const playing=vi.fn();const view=render(<StudioVoice session={session} epoch={1} events={[coach()]} onTranscript={vi.fn()} onPlaybackStateChange={playing} />);
    fireEvent.click(screen.getByRole('button',{name:'Enable coach speech'}));await waitFor(()=>expect(play).toHaveBeenCalled());
    expect(playing).not.toHaveBeenCalledWith(true);
    await act(async()=>begin());expect(playing).toHaveBeenLastCalledWith(true);
    fireEvent.ended(view.container.querySelector('audio')!);expect(playing).toHaveBeenLastCalledWith(false);
  });
  it('bounds replay URLs and revokes evictions and failed media',async()=>{
    const view=mount();await speak();
    for(let sequence=2;sequence<=14;sequence++){
      fireEvent.ended(view.container.querySelector('audio')!);
      view.rerender(<StudioVoice session={session} epoch={1} events={[coach(sequence)]} onTranscript={vi.fn()} />);
      await waitFor(()=>expect(play).toHaveBeenCalledTimes(sequence));
    }
    expect(revokeUrl).toHaveBeenCalledWith('blob:voice-1');expect(revokeUrl).toHaveBeenCalledWith('blob:voice-2');
    fireEvent.error(view.container.querySelector('audio')!);
    expect(revokeUrl).toHaveBeenCalledWith('blob:voice-14');
  });
});
