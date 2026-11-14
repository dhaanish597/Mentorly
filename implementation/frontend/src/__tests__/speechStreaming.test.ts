import { describe, expect, it } from 'vitest';
import { consumeAudioEvents, PcmFrameWriter, StreamingPcmPlayer } from '../services/speechStreaming';
import type { RevisionRef } from '../types/api';

describe('Browser streaming boundaries', () => {
  it('reframes arbitrary worklet quanta as 1024 byte little-endian PCM and pads only the final frame', () => {
    const frames: Uint8Array[] = [];
    const writer = new PcmFrameWriter(frame => frames.push(frame));
    for (let i = 0; i < 13; i++) writer.push(new Int16Array(43).fill(-1234));
    expect(frames).toHaveLength(1); writer.finish(); expect(frames).toHaveLength(2);
    expect(frames.every(frame => frame.length === 1024)).toBe(true);
    expect(new DataView(frames[0].buffer).getInt16(0, true)).toBe(-1234);
    expect(new DataView(frames[1].buffer).getInt16(92, true)).toBe(-1234);
    expect(new DataView(frames[1].buffer).getInt16(94, true)).toBe(0);
  });
  it('parses split SSE fields and rejects a missing terminal event', async () => {
    const raw = 'event: chunk\r\ndata: {"event_type":"chunk","audio_b64":"AAA=","chunk_index":1}\r\n\r\ndata: {"event_type":"complete"}\n\n';
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({ start(controller) { for (const part of raw.match(/.{1,7}/gs) ?? []) controller.enqueue(encoder.encode(part)); controller.close(); } });
    const received: string[] = [];
    await consumeAudioEvents(new Response(stream), event => { received.push(event.event_type); }, new AbortController().signal);
    expect(received).toEqual(['chunk','complete']);
    await expect(consumeAudioEvents(new Response('data: {"event_type":"chunk","audio_b64":"AAA="}\n\n'), () => undefined, new AbortController().signal)).rejects.toThrow('Incomplete');
  });
  it('schedules the first PCM chunk before stream completion and stops scheduled sources', async () => {
    let started = false, stopped = false, closed = false;
    const context = { state: 'running', currentTime: 1, destination: {}, createBuffer: (_channels: number, frames: number, rate: number) => ({ duration: frames / rate, getChannelData: () => new Float32Array(frames) }), createBufferSource: () => ({ buffer: null, connect: () => undefined, disconnect: () => undefined, start: () => { started = true; }, stop: () => { stopped = true; }, onended: null }), close: async () => { closed = true; } } as unknown as AudioContext;
    const revision = { session_id: 's', exercise_id: 'ex1_shortest_subarray', spec_version: 'v1_positive_only', code_version_id: 1, code_hash: 'a'.repeat(64), turn_generation: 1 } as RevisionRef;
    const player = new StreamingPcmPlayer(revision, () => context);
    await player.append({ event_type: 'chunk', request_id: 'provider-id', audio_b64: 'AAAAAA==', chunk_index: 1, sample_rate: 22050 });
    expect(started).toBe(true); await player.stop(); expect(stopped).toBe(true); expect(closed).toBe(true);
    await expect(player.append({ event_type: 'complete', request_id: 'p' })).rejects.toThrow('cancelled');
  });
});
