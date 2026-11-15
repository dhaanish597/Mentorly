import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ModuleVoice } from '../voice/ModuleVoice';
import { saveAudioPreferences, DEFAULT_AUDIO_PREFERENCES, saveSpeechPreferences, DEFAULT_SPEECH_PREFERENCES } from '../voice/preferences';

const mocks = vi.hoisted(() => ({
  start:vi.fn(), stop:vi.fn(), disposeRecorder:vi.fn(), play:vi.fn(), unlock:vi.fn(),
  barge:vi.fn(), disposePlayer:vi.fn(), preferences:vi.fn(), progress:.25, playing:true,
}));
vi.mock('../services/audioRecorder', () => ({AudioRecorder:class {
  startMicrophoneCapture=mocks.start; stopMicrophoneCapture=mocks.stop; dispose=mocks.disposeRecorder;
}}));
vi.mock('../services/audioPlayer', () => ({AudioPlayer:class {
  get playbackProgress(){return mocks.progress;} get isPlaying(){return mocks.playing;}
  playWavBytes=mocks.play; unlockAudioFromGesture=mocks.unlock;
  bargeInStop=mocks.barge; dispose=mocks.disposePlayer; setPreferences=mocks.preferences;
  static buildReadTextFallbackAck(){return null;}
}}));
const props = {module:'lesson' as const,sessionId:'source',epoch:3,workspace:{id:'workspace',token:'capability'},
  messageId:'message',onTranscript:vi.fn()};
function response(data:unknown, status=200){return {ok:status===200,status,json:async()=>data};}
beforeEach(()=>{
  vi.clearAllMocks(); localStorage.clear(); props.onTranscript.mockReset(); mocks.playing=true; mocks.progress=.25;
  mocks.start.mockResolvedValue({}); mocks.stop.mockResolvedValue({wavBytes:new Uint8Array([1,2,3]),lowEnergyWarning:false});
  mocks.disposeRecorder.mockResolvedValue(undefined); mocks.disposePlayer.mockResolvedValue(undefined);
  mocks.unlock.mockResolvedValue(true); mocks.play.mockResolvedValue({started:true,fallbackAck:null});
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response({epoch:3,raw_transcript:'draft',normalized_transcript:'My draft',requires_confirmation:true})));
});
afterEach(()=>{cleanup();vi.unstubAllGlobals();});

describe('source module voice',()=>{
  it('never starts microphone or dispatches speech on mount',()=>{
    render(<ModuleVoice {...props}/>);
    expect(mocks.start).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
    expect(screen.getByRole('button',{name:'Record answer'})).toBeEnabled();
    expect(screen.getByText(/never submitted automatically/i)).toBeInTheDocument();
  });
  it('preserves a new capture when stopped recorder cleanup finishes after immediate retry',async()=>{
    const samples=new WeakMap<object,Uint8Array>();
    let attempt=0;
    let releaseOldCleanup:()=>void=()=>{throw new Error('Old cleanup did not start');};
    let pendingOldCleanup=true;
    mocks.start.mockImplementation(function(this:object){
      samples.set(this,++attempt===1 ? new Uint8Array([1,2,3]) : new Uint8Array([4,5,6]));
      return Promise.resolve({});
    });
    mocks.stop.mockImplementation(function(this:object){
      const wavBytes=samples.get(this);
      if(!wavBytes) throw new Error('New capture samples were erased by stale cleanup');
      return Promise.resolve({wavBytes,lowEnergyWarning:false});
    });
    mocks.disposeRecorder.mockImplementation(function(this:object){
      const owner=this;
      if(pendingOldCleanup){
        pendingOldCleanup=false;
        return new Promise<void>(resolve=>{releaseOldCleanup=()=>{samples.delete(owner);resolve();};});
      }
      samples.delete(owner);
      return Promise.resolve();
    });
    render(<ModuleVoice {...props}/>);
    fireEvent.click(screen.getByRole('button',{name:'Record answer'}));
    await screen.findByRole('button',{name:'Stop recording'});
    fireEvent.click(screen.getByRole('button',{name:'Stop voice'}));
    fireEvent.click(screen.getByRole('button',{name:'Record answer'}));
    await screen.findByRole('button',{name:'Stop recording'});
    await act(async()=>{releaseOldCleanup();});
    fireEvent.click(screen.getByRole('button',{name:'Stop recording'}));
    await waitFor(()=>expect(props.onTranscript).toHaveBeenCalledWith('My draft'));
    expect(JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body)).audio_base64).toBe('BAUG');
  });
  it('records only by consent and returns recognized text as a draft using workspace capability',async()=>{
    render(<ModuleVoice {...props}/>);
    fireEvent.click(screen.getByRole('button',{name:'Record answer'}));
    await screen.findByRole('button',{name:'Stop recording'});
    fireEvent.click(screen.getByRole('button',{name:'Stop recording'}));
    await waitFor(()=>expect(props.onTranscript).toHaveBeenCalledWith('My draft'));
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url,options] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe('/api/v1/module-voice/lesson/source/stt');
    expect(options?.headers).toMatchObject({'X-Workspace-Id':'workspace','X-Workspace-Token':'capability'});
    expect(JSON.parse(String(options?.body))).toEqual({epoch:3,audio_base64:'AQID',language_mode:'en-IN'});
  });
  it('honors shared language/voice selection and only sends persisted message identity',async()=>{
    saveSpeechPreferences({...DEFAULT_SPEECH_PREFERENCES,sttLanguage:'ta-IN',spokenLanguage:'ta-IN',codeMixing:true,voice:'Shivani'});
    vi.mocked(fetch).mockResolvedValue(response({epoch:3,audio_base64:'AQID',content_type:'audio/wav'}) as Response);
    render(<ModuleVoice {...props}/>);
    fireEvent.click(screen.getByRole('button',{name:'Listen to coach'}));
    await waitFor(()=>expect(mocks.play).toHaveBeenCalled());
    const [,options] = vi.mocked(fetch).mock.calls[0];
    expect(JSON.parse(String(options?.body))).toEqual({epoch:3,message_id:'message',language:'ta-IN',voice:'Shivani'});
    expect(mocks.unlock).toHaveBeenCalledTimes(1);
  });
  it('cancels old network, capture, and playback on source epoch change',async()=>{
    vi.mocked(fetch).mockImplementation(()=>new Promise(()=>undefined));
    const view=render(<ModuleVoice {...props}/>);
    fireEvent.click(screen.getByRole('button',{name:'Record answer'}));
    fireEvent.click(await screen.findByRole('button',{name:'Stop recording'}));
    await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(1));
    const signal=vi.mocked(fetch).mock.calls[0][1]?.signal;
    view.rerender(<ModuleVoice {...props} epoch={4}/>);
    expect(signal?.aborted).toBe(true); expect(mocks.disposeRecorder).toHaveBeenCalled();
    expect(mocks.disposePlayer).toHaveBeenCalled(); expect(props.onTranscript).not.toHaveBeenCalled();
  });
  it('reacts to text-only preference changes and suppresses paid playback',async()=>{
    render(<ModuleVoice {...props}/>);
    act(()=>{saveAudioPreferences({...DEFAULT_AUDIO_PREFERENCES,textOnly:true});});
    expect(screen.getByRole('button',{name:'Listen to coach'})).toBeDisabled();
    expect(screen.getByRole('button',{name:'Record answer'})).toBeDisabled();
    expect(fetch).not.toHaveBeenCalled();
  });
  it('uses real playback progress and ends bounded local replay without another provider call',async()=>{
    vi.mocked(fetch).mockResolvedValue(response({epoch:3,audio_base64:'AQID',content_type:'audio/wav'}) as Response);
    render(<ModuleVoice {...props}/>);
    fireEvent.click(screen.getByRole('button',{name:'Listen to coach'}));
    await screen.findByRole('progressbar');
    mocks.progress=.7;
    await waitFor(()=>expect(screen.getByRole('progressbar')).toHaveAttribute('value','0.7'));
    fireEvent.click(screen.getByRole('button',{name:'Stop voice'}));
    fireEvent.click(screen.getByRole('button',{name:'Listen to coach'}));
    await screen.findByRole('progressbar');
    mocks.playing=false;
    await waitFor(()=>expect(screen.queryByRole('progressbar')).not.toBeInTheDocument());
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('ignores retired recorder callbacks and finalizes only the current capture',async()=>{
    type Callbacks={onSilenceTimeout:()=>void;onBackpressureLimitReached:()=>void;onDeviceLost:()=>void};
    render(<ModuleVoice {...props}/>);
    fireEvent.click(screen.getByRole('button',{name:'Record answer'}));
    await screen.findByRole('button',{name:'Stop recording'});
    const retired=mocks.start.mock.calls[0][0] as Callbacks;
    fireEvent.click(screen.getByRole('button',{name:'Stop voice'}));
    fireEvent.click(screen.getByRole('button',{name:'Record answer'}));
    await screen.findByRole('button',{name:'Stop recording'});
    act(()=>{retired.onSilenceTimeout();retired.onBackpressureLimitReached();retired.onDeviceLost();});
    expect(fetch).not.toHaveBeenCalled(); expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('button',{name:'Stop recording'})).toBeEnabled();
    const current=mocks.start.mock.calls[1][0] as Callbacks;
    act(()=>{current.onSilenceTimeout();current.onBackpressureLimitReached();});
    await waitFor(()=>expect(props.onTranscript).toHaveBeenCalledWith('My draft'));
    expect(mocks.stop).toHaveBeenCalledTimes(1);
  });
  it('handles device loss without dispatching an answer',async()=>{
    render(<ModuleVoice {...props}/>);
    fireEvent.click(screen.getByRole('button',{name:'Record answer'}));
    await screen.findByRole('button',{name:'Stop recording'});
    const options=mocks.start.mock.calls[0][0] as {onDeviceLost:()=>void};
    act(()=>{options.onDeviceLost();});
    expect(screen.getByRole('alert')).toHaveTextContent(/disconnected/);
    expect(fetch).not.toHaveBeenCalled();
  });
  it('rejects malformed or invalid audio responses without caching failed playback',async()=>{
    vi.mocked(fetch).mockResolvedValue(response({epoch:3,audio_base64:'',content_type:'audio/wav'}) as Response);
    render(<ModuleVoice {...props}/>);
    fireEvent.click(screen.getByRole('button',{name:'Listen to coach'}));
    expect(await screen.findByRole('alert')).toHaveTextContent(/Invalid voice audio/);
    expect(mocks.play).not.toHaveBeenCalled();
  });
  it('shows quiet recording notice and handles capture permission failure without networking',async()=>{
    mocks.start.mockRejectedValueOnce(new Error('Microphone denied. Continue with text.'));
    render(<ModuleVoice {...props}/>);
    fireEvent.click(screen.getByRole('button',{name:'Record answer'}));
    expect(await screen.findByRole('alert')).toHaveTextContent(/Microphone denied/);
    expect(fetch).not.toHaveBeenCalled();
  });
  it('rejects non-final or stale recognition without changing the draft',async()=>{
    vi.mocked(fetch).mockResolvedValue(response({epoch:2,normalized_transcript:'stale',requires_confirmation:false}) as Response);
    render(<ModuleVoice {...props}/>);
    fireEvent.click(screen.getByRole('button',{name:'Record answer'}));
    fireEvent.click(await screen.findByRole('button',{name:'Stop recording'}));
    expect(await screen.findByRole('alert')).toHaveTextContent(/superseded or invalid/);
    expect(props.onTranscript).not.toHaveBeenCalled();
  });
  it('reacts to speech preference changes by closing consented capture',async()=>{
    render(<ModuleVoice {...props}/>);
    fireEvent.click(screen.getByRole('button',{name:'Record answer'}));
    await screen.findByRole('button',{name:'Stop recording'});
    act(()=>{saveSpeechPreferences({...DEFAULT_SPEECH_PREFERENCES,spokenLanguage:'ta-IN'});});
    expect(screen.getByRole('button',{name:'Record answer'})).toBeEnabled();
    expect(mocks.disposeRecorder).toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
  });
  it('does not dispatch TTS when gesture audio activation is blocked',async()=>{
    mocks.unlock.mockResolvedValue(false);
    render(<ModuleVoice {...props}/>);
    fireEvent.click(screen.getByRole('button',{name:'Listen to coach'}));
    expect(await screen.findByRole('alert')).toHaveTextContent(/playback is blocked/);
    expect(fetch).not.toHaveBeenCalled();
  });
  it('leaves draft unchanged when backend reports unavailable',async()=>{
    vi.mocked(fetch).mockResolvedValue(response({detail:'Cloud speech unavailable'},503) as Response);
    render(<ModuleVoice {...props}/>);
    fireEvent.click(screen.getByRole('button',{name:'Record answer'}));
    fireEvent.click(await screen.findByRole('button',{name:'Stop recording'}));
    expect(await screen.findByRole('alert')).toHaveTextContent(/continue with text/i);
    expect(props.onTranscript).not.toHaveBeenCalled();
  });
});
