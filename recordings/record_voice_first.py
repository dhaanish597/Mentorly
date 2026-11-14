"""Record actual mentor playback and synthesized learner via a virtual microphone."""
from __future__ import annotations
import asyncio
import base64
import json
import subprocess
import time
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent
INSTRUMENTATION = r"""
(() => {
  const tracks=[]; window.__tracks=tracks; window.__events=[]; const origin=Date.now();
  function record(stream,kind) {
    const chunks=[]; const recorder=new MediaRecorder(stream,{mimeType:'audio/webm;codecs=opus'});
    const entry={kind,offset:(Date.now()-origin)/1000,recorder,chunks};
    recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};
    tracks.push(entry); recorder.start(100);
  }
  const connect=AudioNode.prototype.connect; const destinations=new WeakMap();
  AudioNode.prototype.connect=function(target,...args) {
    const result=connect.call(this,target,...args);
    if(target instanceof AudioDestinationNode) {
      let destination=destinations.get(this.context);
      if(!destination){destination=this.context.createMediaStreamDestination();destinations.set(this.context,destination);record(destination.stream,'mentor')}
      connect.call(this,destination);
    }
    return result;
  };
  const start=AudioBufferSourceNode.prototype.start;
  AudioBufferSourceNode.prototype.start=function(...args){if(this.buffer&&!this.context.__learner)window.__events.push({kind:'mentor-start',at:(Date.now()-origin)/1000,duration:this.buffer.duration});return start.apply(this,args)};
  let microphone;
  navigator.mediaDevices.getUserMedia=async()=>{
    if(!microphone){const context=new AudioContext({sampleRate:48000});context.__learner=true;await context.resume();const destination=context.createMediaStreamDestination();microphone={context,destination};record(destination.stream,'learner')}
    return microphone.destination.stream;
  };
  window.__speak=async encoded=>{
    const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));const buffer=await microphone.context.decodeAudioData(bytes.buffer);
    const source=microphone.context.createBufferSource();source.buffer=buffer;source.connect(microphone.destination);
    window.__events.push({kind:'learner-start',at:(Date.now()-origin)/1000,duration:buffer.duration});source.start();return buffer.duration;
  };
  window.__finish=async()=>Promise.all(tracks.map(async e=>{
    await new Promise(resolve=>{e.recorder.onstop=resolve;e.recorder.stop()});const bytes=new Uint8Array(await new Blob(e.chunks).arrayBuffer());
    let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));return {kind:e.kind,offset:e.offset,base64:btoa(binary)};
  }));
})();
"""


def mux(raw: Path, tracks: list[dict], duration: float) -> Path:
    output=ROOT/'viva_voice_first_demo.mp4'
    command=['ffmpeg','-y','-loglevel','error','-i',str(raw)]
    for track in tracks:
        command+=['-i',track['path']]
    filters=[f"[{i+1}:a]adelay={round(t['offset']*1000)}:all=1[a{i}]" for i,t in enumerate(tracks)]
    filters.append(''.join(f'[a{i}]' for i in range(len(tracks)))+f'amix=inputs={len(tracks)}:normalize=0:dropout_transition=0,apad[audio]')
    command+=['-filter_complex',';'.join(filters),'-map','0:v','-map','[audio]','-t',str(duration),'-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k',str(output)]
    subprocess.run(command,check=True)
    return output


async def main() -> None:
    evidence={'learner_voice':'Synthesized voice through virtual microphone, real AudioWorklet/STT; no transcript injection','mentor_voice':'Actual app WebAudio playback and backend TTS','requests':[],'errors':[]}
    clips=[base64.b64encode((ROOT/f'voice-first-learner-{i}.wav').read_bytes()).decode() for i in (1,2)]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,args=['--autoplay-policy=no-user-gesture-required','--use-fake-ui-for-media-stream'])
        context=await browser.new_context(viewport={'width':1440,'height':900},record_video_dir=str(ROOT/'voice-first-raw'),record_video_size={'width':1440,'height':900},permissions=['microphone'])
        await context.add_init_script(INSTRUMENTATION)
        page=await context.new_page()
        async def response_received(response):
            if '/api/v1/' in response.url and response.request.method=='POST':
                entry={'path':response.url.split('/api/v1/')[1],'status':response.status}
                if '/turns/audio' in response.url:
                    entry['transcript']=(await response.json()).get('transcript')
                evidence['requests'].append(entry);print(json.dumps(entry),flush=True)
        page.on('response',response_received)
        page.on('pageerror',lambda error:evidence['errors'].append(str(error)))
        started=time.monotonic()
        try:
            await page.goto('http://127.0.0.1:5181/practice/ex1_shortest_subarray?spec=v1_positive_only',wait_until='networkidle')
            await page.wait_for_selector('.is-speaking',timeout=60000)
            print('Opening greeting is playing',flush=True)
            await page.wait_for_function("!document.querySelector('.is-speaking')",timeout=60000)
            await page.screenshot(path=str(ROOT/'voice-first-workspace.png'))
            if await page.get_by_role('button',name='Stop / Barge-In',exact=True).count():
                raise RuntimeError('Voice panel must not contain a second stop/send control')
            await page.locator('.voice-turn-button').click()
            await page.wait_for_selector('.is-recording')
            duration=await page.evaluate('window.__speak',clips[0])
            await page.wait_for_timeout(duration*1000+10000)
            print('Waiting for reply after ten seconds quiet',flush=True)
            await page.wait_for_selector('.is-speaking',timeout=60000)
            await page.wait_for_timeout(1200)
            duration=await page.evaluate('window.__speak',clips[1])
            await page.wait_for_function("!document.querySelector('.is-speaking')",timeout=5000)
            evidence['barge_in_stopped_mentor']=True
            print('Barge-in stops mentor; microphone keeps recording',flush=True)
            await page.wait_for_timeout(duration*1000+10000)
            await page.wait_for_selector('.is-speaking',timeout=60000)
            await page.wait_for_function("!document.querySelector('.is-speaking')",timeout=60000)
            await page.locator('.voice-text-toggle').click()
            evidence['retained_transcript']=await page.locator("textarea[aria-label='Editable Learner Transcript']").input_value()
            if 'finish my thought' not in evidence['retained_transcript'].lower() or 'right boundary' not in evidence['retained_transcript'].lower():
                raise RuntimeError('Both learner speech segments must remain in the visible transcript')
            await page.screenshot(path=str(ROOT/'voice-first-preserved-speech.png'))
            await page.locator('.voice-text-toggle').click()
            await page.get_by_role('button',name='Submit code',exact=True).click()
            await page.wait_for_timeout(3000)
            evidence['code_submit_state']=await page.locator('#results-pane').inner_text()
            await page.screenshot(path=str(ROOT/'voice-first-submit-code.png'))
            await page.wait_for_timeout(2000)
        except Exception as error:
            evidence['errors'].append(str(error));await page.screenshot(path=str(ROOT/'voice-first-recording-error.png'));print(f'Journey error: {error}',flush=True)
        evidence['audio_events']=await page.evaluate('window.__events')
        recorded=await page.evaluate('window.__finish()')
        tracks=[]
        for i,entry in enumerate(recorded):
            path=ROOT/f"voice-first-live-{i}-{entry['kind']}.webm"
            path.write_bytes(base64.b64decode(entry.pop('base64')));tracks.append({**entry,'path':str(path)})
        raw=Path(await page.video.path());duration=time.monotonic()-started
        await context.close();await browser.close()
    evidence['recorded_audio_tracks']=tracks
    output=mux(raw,tracks,duration);evidence['video']=str(output)
    (ROOT/'voice-first-evidence.json').write_text(json.dumps(evidence,indent=2))
    print(f'Recorded {output} ({output.stat().st_size} bytes)',flush=True)
    if evidence['errors']:
        raise RuntimeError('Incomplete journey; inspect evidence report')


if __name__=='__main__':
    asyncio.run(main())
