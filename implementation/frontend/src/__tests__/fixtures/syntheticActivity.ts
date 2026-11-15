export function voiceLike(rate = 48000, seconds = .9, offset = 0): Float32Array {
  return Float32Array.from({ length: Math.round(rate * seconds) }, (_, i) => {
    const t = offset + i / rate;
    const envelope = .11 + .075 * Math.sin(2 * Math.PI * 5 * t);
    return envelope * (Math.sin(2 * Math.PI * 220 * t) + .4 * Math.sin(2 * Math.PI * 660 * t));
  });
}
