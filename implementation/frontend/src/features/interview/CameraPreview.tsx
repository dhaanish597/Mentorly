import { useEffect, useRef, useState } from 'react';

type CameraPreviewProps = { disabled?: boolean };
/** Never records, uploads or assesses images. A pending permission is cleaned too. */
export function CameraPreview({ disabled = false }: CameraPreviewProps): JSX.Element {
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const generation = useRef(0);
  const [state, setState] = useState<'off' | 'requesting' | 'on'>('off');
  const [error, setError] = useState('');
  useEffect(() => () => {
    generation.current += 1;
    stream.current?.getTracks().forEach(track => track.stop());
    stream.current = null;
  }, []);
  useEffect(() => {
    if (video.current) video.current.srcObject = state === 'on' ? stream.current : null;
  }, [state]);
  async function enable(): Promise<void> {
    const request = ++generation.current;
    setState('requesting'); setError('');
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Camera preview is unavailable. You can continue without it.');
      const next = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      if (request !== generation.current) { next.getTracks().forEach(track => track.stop()); return; }
      stream.current = next; setState('on');
    } catch (error) {
      if (request !== generation.current) return;
      setState('off'); setError(error instanceof Error ? error.message : 'Camera permission was not granted. Continue without a camera.');
    }
  }
  function stop(): void {
    generation.current += 1;
    stream.current?.getTracks().forEach(track => track.stop());
    stream.current = null; setState('off');
  }
  return <aside className="interview-camera" aria-labelledby="camera-title">
    <h2 id="camera-title">Your space, your choice</h2>
    <p>Camera off by default. Preview stays on this device; it is not recorded, uploaded or assessed.</p>
    {state === 'on' && <video ref={video} autoPlay muted playsInline aria-label="Local camera preview" />}
    {error && <p role="alert">{error}</p>}
    {state === 'off' ? <button type="button" disabled={disabled} onClick={() => void enable()}>Enable local camera preview</button> :
      <button type="button" onClick={stop}>{state === 'requesting' ? 'Cancel camera request' : 'Turn camera off'}</button>}
    <p role="status">{state === 'requesting' ? 'Waiting for camera permission…' : state === 'on' ? 'Local preview on' : 'Camera off'}</p>
  </aside>;
}
