import { describe, expect, it, vi } from 'vitest';
import { StreamingPcmPlayer, consumeAudioEvents } from '../services/speechStreaming';
import { encodePcm16ToWavBytes } from '../services/audioRecorder';
import { AudioPlayer } from '../services/audioPlayer';
import { DEFAULT_AUDIO_PREFERENCES } from '../voice/preferences';
import type { RevisionRef } from '../types/api';

const revision: RevisionRef={session_id:'11111111-1111-1111-1111-111111111111',exercise_id:'ex1_shortest_subarray',spec_version:'v1_positive_only',code_hash:'a'.repeat(64),code_version_id:1,turn_generation:0};
function audioContext() {
  const sources: {buffer:AudioBuffer|null;playbackRate:{value:number};connect:ReturnType<typeof vi.fn>;disconnect:ReturnType<typeof vi.fn>;stop:ReturnType<typeof vi.fn>;start:ReturnType<typeof vi.fn>;onended:(()=>void)|null}[]=[];
  const gain={gain:{value:1},connect:vi.fn(),disconnect:vi.fn()};
  const ctx={state:'running',currentTime:0,destination:{},resume:vi.fn(),close:vi.fn(),createGain:()=>gain,
    createBuffer:(_channels:number,frames:number,rate:number)=>({duration:frames/rate,getChannelData:()=>new Float32Array(frames)}),
    createBufferSource:()=>{const source={buffer:null,playbackRate:{value:1},connect:vi.fn(),disconnect:vi.fn(),stop:vi.fn(),start:vi.fn(),onended:null};sources.push(source);return source;}};
  return {ctx:ctx as unknown as AudioContext,sources,gain};
}

describe('stream preferences and resource cleanup',()=>{
  it('cancels a stalled response immediately rather than awaiting another network chunk',async()=>{
    const cancelled=vi.fn();
    const response=new Response(new ReadableStream({cancel:cancelled}));
    const abort=new AbortController();
    const pending=consumeAudioEvents(response,()=>undefined,abort.signal);
    abort.abort();
    await expect(pending).rejects.toMatchObject({name:'AbortError'});
    expect(cancelled).toHaveBeenCalled();
  });
  it('accepts cached WAV completion and applies gain and local playback speed',async()=>{
    const wav=encodePcm16ToWavBytes(new Int16Array([100,200,300]),16000);
    const encoded=btoa(String.fromCharCode(...wav));
    const event={event_type:'complete' as const,request_id:'cached',wav_bytes_b64:encoded,cache_hit:true,sample_rate:16000};
    const delivered=vi.fn();
    await consumeAudioEvents(new Response(`data: ${JSON.stringify(event)}\n\n`),delivered,new AbortController().signal);
    expect(delivered).toHaveBeenCalledOnce();
    const {ctx,sources,gain}=audioContext();
    const player=new StreamingPcmPlayer(revision,()=>ctx);
    player.setPreferences({...DEFAULT_AUDIO_PREFERENCES,volume:.3,speed:1.5});
    await player.append(event);
    expect(gain.gain.value).toBe(.3);
    expect(sources[0].playbackRate.value).toBe(1.5);
    const finish=player.finish();
    sources[0].onended?.();
    await finish;
    await player.stop();
    expect(ctx.close).toHaveBeenCalledOnce();
  });
  it('WAV player applies gain/rate and mute prevents scheduling',async()=>{
    const {ctx,sources,gain}=audioContext();
    const player=new AudioPlayer();
    const params={sessionId:'s',turnId:'intro',turnGeneration:0,wavBytes:encodePcm16ToWavBytes(new Int16Array([100]),16000),audioContextFactory:()=>ctx};
    player.setPreferences({...DEFAULT_AUDIO_PREFERENCES,volume:.2,speed:2});
    expect((await player.playWavBytes(params)).started).toBe(true);
    expect(gain.gain.value).toBe(.2);
    expect(sources[0].playbackRate.value).toBe(2);
    player.setPreferences({...DEFAULT_AUDIO_PREFERENCES,muted:true});
    expect(sources[0].stop).toHaveBeenCalled();
    expect((await player.playWavBytes(params)).started).toBe(false);
    expect(sources.length).toBe(1);
    await player.dispose();
  });
});
