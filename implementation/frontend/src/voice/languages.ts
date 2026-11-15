/** Provider-documented catalog. This is not a live account/credit verification. */
export const SPEECH_LANGUAGES = Object.freeze([
  {code:'en-IN',label:'English'}, {code:'hi-IN',label:'Hindi'},
  {code:'ta-IN',label:'Tamil'}, {code:'te-IN',label:'Telugu'},
  {code:'kn-IN',label:'Kannada'}, {code:'ml-IN',label:'Malayalam'},
  {code:'bn-IN',label:'Bengali'}, {code:'gu-IN',label:'Gujarati'},
  {code:'mr-IN',label:'Marathi'}, {code:'pa-IN',label:'Punjabi'},
] as const);
export type SpeechLocale = typeof SPEECH_LANGUAGES[number]['code'];
export type ProductLanguageMode = SpeechLocale | 'ta-IN,en-IN' | 'hi-IN,en-IN' | 'bn-IN,en-IN';
export const PRODUCT_LANGUAGES: readonly {code: ProductLanguageMode; label: string}[] = Object.freeze([
  ...SPEECH_LANGUAGES, {code:'ta-IN,en-IN', label:'Tanglish'},
  {code:'hi-IN,en-IN', label:'Hindi-English'}, {code:'bn-IN,en-IN', label:'Bengali-English'},
]);
export function isProductLanguageMode(value: unknown): value is ProductLanguageMode {
  return PRODUCT_LANGUAGES.some(item => item.code === value);
}
export function languageModeLabel(value: string): string {
  return PRODUCT_LANGUAGES.find(item => item.code === value)?.label ?? 'Unsupported language';
}
export function recognitionLocale(value: ProductLanguageMode): SpeechLocale {
  const locale = value.split(',')[0];
  if (!isSpeechLocale(locale)) throw new Error('Unsupported speech language.');
  return locale;
}
export const TTS_VOICES = Object.freeze(['Avinash','Shivani','Lakshmi','Kalpana','Shubham','Prakash','Devansh','Yashraj','Chetana','Vasudha','Riyaa','Tarika','Harshad'] as const);
export type TTSVoice = typeof TTS_VOICES[number];
export const CODE_MIXING_LANGUAGES: readonly SpeechLocale[] = Object.freeze(['ta-IN','hi-IN','bn-IN']);
export interface SpeechSelection {
  readonly sttLanguage: SpeechLocale;
  readonly spokenLanguage: SpeechLocale;
  readonly codeMixing: boolean;
  readonly voice: TTSVoice;
}
export interface ResolvedSpeechSelection {
  readonly language_mode: ProductLanguageMode;
  readonly spoken_language: SpeechLocale;
  readonly language: SpeechLocale;
  readonly voice: TTSVoice;
  readonly model: 'timbre-v3.0';
}
export function isSpeechLocale(value: unknown): value is SpeechLocale {
  return SPEECH_LANGUAGES.some(item => item.code === value);
}
export function isTTSVoice(value: unknown): value is TTSVoice {
  return TTS_VOICES.some(voice => voice === value);
}
export function resolveLanguageMode(sttLanguage: SpeechLocale, codeMixing: boolean): ProductLanguageMode {
  if (!isSpeechLocale(sttLanguage)) throw new Error('Unsupported speech language.');
  if (!codeMixing) return sttLanguage;
  if (!CODE_MIXING_LANGUAGES.includes(sttLanguage)) throw new Error('Code mixing is not enabled for this language.');
  return `${sttLanguage},en-IN` as ProductLanguageMode;
}
export function resolveSpeechSelection(selection: SpeechSelection): ResolvedSpeechSelection {
  if (!isSpeechLocale(selection.spokenLanguage) || !isTTSVoice(selection.voice)) throw new Error('Unsupported spoken language or voice.');
  return Object.freeze({language_mode:resolveLanguageMode(selection.sttLanguage, selection.codeMixing),
    spoken_language:selection.spokenLanguage, language:selection.spokenLanguage, voice:selection.voice, model:'timbre-v3.0'});
}
export interface SpeechCapabilities {
  readonly documented: boolean;
  readonly live_unverified: boolean;
  readonly configured: boolean;
  readonly stt_model: string;
  readonly tts_model: string;
  readonly language_modes?: readonly ProductLanguageMode[];
  readonly languages: readonly {code:SpeechLocale; label:string; documented:boolean; live_unverified:boolean; compatible_voices:readonly TTSVoice[]; code_mixing:boolean}[];
  readonly voices: readonly {id:TTSVoice; model:string; languages:readonly SpeechLocale[]; documented:boolean; live_unverified:boolean}[];
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function parseCapabilities(value: unknown): SpeechCapabilities {
  if (!isRecord(value) || typeof value.documented !== 'boolean' || typeof value.live_unverified !== 'boolean'
    || typeof value.configured !== 'boolean' || value.stt_model !== 'prisma-v3.0' || value.tts_model !== 'timbre-v3.0'
    || !Array.isArray(value.languages) || !Array.isArray(value.voices)
    || !value.languages.length || !value.voices.length) throw new Error('Invalid speech capability registry.');
  if (value.language_modes !== undefined && (!Array.isArray(value.language_modes) || !value.language_modes.length || !value.language_modes.every(isProductLanguageMode))) throw new Error('Invalid language modes.');
  for (const item of value.languages) {
    if (!isRecord(item) || !isSpeechLocale(item.code) || typeof item.label !== 'string'
      || typeof item.documented !== 'boolean' || typeof item.live_unverified !== 'boolean'
      || typeof item.code_mixing !== 'boolean' || !Array.isArray(item.compatible_voices)
      || !item.compatible_voices.every(isTTSVoice)) throw new Error('Invalid speech language capability.');
  }
  for (const item of value.voices) {
    if (!isRecord(item) || !isTTSVoice(item.id) || item.model !== 'timbre-v3.0'
      || typeof item.documented !== 'boolean' || typeof item.live_unverified !== 'boolean'
      || !Array.isArray(item.languages) || !item.languages.every(isSpeechLocale)) throw new Error('Invalid speech voice capability.');
  }
  return value as unknown as SpeechCapabilities;
}
export async function fetchSpeechCapabilities(apiBase = '/api/v1', signal?: AbortSignal): Promise<SpeechCapabilities> {
  const response = await fetch(`${apiBase.replace(/\/$/,'')}/speech/capabilities`, {signal});
  if (!response.ok) throw new Error('Speech capability information is unavailable. Continue with text.');
  return parseCapabilities(await response.json());
}
