import { PRODUCT_LANGUAGES, SPEECH_LANGUAGES, TTS_VOICES, type SpeechCapabilities } from '../../voice/languages';

/** Documented test catalog only: no provider readiness or real credit claim. */
export const speechCapabilitiesFixture: SpeechCapabilities = {
  documented:true, live_unverified:true, configured:false, stt_model:'prisma-v3.0', tts_model:'timbre-v3.0',
  language_modes:PRODUCT_LANGUAGES.map(item => item.code),
  languages:SPEECH_LANGUAGES.map(item => ({...item,documented:true,live_unverified:true,
    compatible_voices:TTS_VOICES,code_mixing:['ta-IN','hi-IN','bn-IN'].includes(item.code)})),
  voices:TTS_VOICES.map(id => ({id,model:'timbre-v3.0',languages:SPEECH_LANGUAGES.map(item => item.code),documented:true,live_unverified:true})),
};
