import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';
import { Icon, type IconName } from '../../components/HorizonVisuals';
import { navigate } from '../../components/ProductShell';
import { DEFAULT_PRODUCT_STATE, loadProductState, saveProductState, type ThemePreference } from '../../state/productState';
import { DEFAULT_AUDIO_PREFERENCES, DEFAULT_SPEECH_PREFERENCES, loadAudioPreferences, loadSpeechPreferences, saveAudioPreferences, saveSpeechPreferences, subscribeAudioPreferences, subscribeSpeechPreferences, updateAudioPreferences, updateSpeechPreferences, type AudioPreferences, type SpeechPreferences } from '../../voice/preferences';
import { CODE_MIXING_LANGUAGES, SPEECH_LANGUAGES, TTS_VOICES, isSpeechLocale, isTTSVoice } from '../../voice/languages';
import { resetInterviewPreferences } from '../interview/preferences';
import { saveInputDeviceId } from '../../voice/inputDevices';
import { InterviewDefaults } from './InterviewDefaults';
import { MicrophoneCheck } from './MicrophoneCheck';
import { WorkspaceRecovery } from './WorkspaceRecovery';

const categories: { id: string; title: string; icon: IconName; description: string }[] = [
  { id: 'voice', title: 'Voice & Audio', icon: 'mic', description: 'Make your mentor sound right for you.' },
  { id: 'language', title: 'Language', icon: 'book', description: 'Think and explain in a language that feels natural.' },
  { id: 'learning', title: 'Learning', icon: 'paths', description: 'A pace that grows with your understanding.' },
  { id: 'interview', title: 'Interview defaults', icon: 'compass', description: 'Set a reusable brief without changing an active interview.' },
  { id: 'appearance', title: 'Appearance', icon: 'settings', description: 'A comfortable space to focus.' },
  { id: 'privacy', title: 'Privacy', icon: 'shield', description: 'Know what stays on your device and in your workspace.' },
  { id: 'advanced', title: 'Advanced', icon: 'refresh', description: 'Restore your preferences without losing your learning.' },
];
const nativeLanguageNames: Record<string, string> = {
  'hi-IN': 'हिन्दी', 'ta-IN': 'தமிழ்', 'te-IN': 'తెలుగు', 'kn-IN': 'ಕನ್ನಡ', 'ml-IN': 'മലയാളം',
  'bn-IN': 'বাংলা', 'gu-IN': 'ગુજરાતી', 'mr-IN': 'मराठी', 'pa-IN': 'ਪੰਜਾਬੀ',
};
function languageLabel(code: string, label: string): string { return nativeLanguageNames[code] ? `${label} · ${nativeLanguageNames[code]}` : label; }
function SettingRow({ title, detail, children }: { title: string; detail: string; children: ReactNode }) {
  return <div className="setting-row"><div><h3>{title}</h3><p>{detail}</p></div><div className="setting-control">{children}</div></div>;
}
export function SettingsPage({ search = '' }: { search?: string }) {
  const categoryId = new URLSearchParams(search).get('category') ?? 'voice';
  const category = categories.find(item => item.id === categoryId) ?? categories[0];
  const [audio, setAudio] = useState(loadAudioPreferences);
  const [speech, setSpeech] = useState(loadSpeechPreferences);
  const [theme, setTheme] = useState(() => loadProductState().theme);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const confirm = useRef<HTMLButtonElement>(null);
  useEffect(() => subscribeAudioPreferences(setAudio), []);
  useEffect(() => subscribeSpeechPreferences(setSpeech), []);
  useEffect(() => { if (confirmReset) confirm.current?.focus(); }, [confirmReset]);
  function saved(ok: boolean, success = 'Saved on this device') { setError(ok ? null : 'Your preferences could not be saved on this device. Keep this tab open and try again.'); setNotice(ok ? success : null); }
  function changeAudio(patch: Partial<AudioPreferences>) { const next = updateAudioPreferences(audio, patch); setAudio(next); saved(saveAudioPreferences(next)); }
  function changeSpeech(patch: Partial<SpeechPreferences>) { const next = updateSpeechPreferences(speech, patch); setSpeech(next); saved(saveSpeechPreferences(next)); }
  function changeTheme(value: ThemePreference) {
    setTheme(value);
    const message = saveProductState({ ...loadProductState(), theme: value });
    const dark = window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
    document.documentElement.dataset.theme = value === 'system' ? dark ? 'dark' : 'light' : value;
    window.dispatchEvent(new Event('viva:preferences-changed'));
    saved(message === null);
  }
  function resetPreferences() {
    const audioSaved = saveAudioPreferences(DEFAULT_AUDIO_PREFERENCES);
    const speechSaved = saveSpeechPreferences(DEFAULT_SPEECH_PREFERENCES);
    const interviewSaved = resetInterviewPreferences();
    const microphoneSaved = saveInputDeviceId(null);
    const productSaved = saveProductState({ ...loadProductState(), theme: DEFAULT_PRODUCT_STATE.theme, inputChoice: null, alwaysVoiceOn: false, language: DEFAULT_PRODUCT_STATE.language, statementWidth: DEFAULT_PRODUCT_STATE.statementWidth, coachWidth: DEFAULT_PRODUCT_STATE.coachWidth, resultsHeight: DEFAULT_PRODUCT_STATE.resultsHeight, coachCollapsed: false });
    setAudio(DEFAULT_AUDIO_PREFERENCES); setSpeech(DEFAULT_SPEECH_PREFERENCES); setTheme('system'); setConfirmReset(false);
    document.documentElement.dataset.theme = window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    window.dispatchEvent(new Event('viva:preferences-changed'));
    saved(audioSaved && speechSaved && interviewSaved && microphoneSaved && productSaved === null, 'Preferences reset. Your drafts, bookmarks, and workspace are unchanged.');
  }
  function categoryKey(event: KeyboardEvent<HTMLAnchorElement>, index: number) {
    const offset = event.key === 'ArrowDown' || event.key === 'ArrowRight' ? 1 : event.key === 'ArrowUp' || event.key === 'ArrowLeft' ? -1 : 0;
    if (!offset && event.key !== 'Home' && event.key !== 'End') return;
    event.preventDefault();
    const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? categories.length - 1 : (index + offset + categories.length) % categories.length;
    const next = categories[nextIndex];
    navigate(`/settings?category=${next.id}`);
    document.getElementById(`settings-${next.id}`)?.focus();
  }
  let content: ReactNode;
  if (category.id === 'voice') content = <>
    <SettingRow title="Listen or read" detail="Text-only mode never requests audio playback. Your mentor’s words stay visible."><label className="setting-toggle"><input type="checkbox" checked={audio.textOnly} onChange={event => changeAudio({ textOnly: event.target.checked })} /><span>Text-only mode</span></label></SettingRow>
    <SettingRow title="Mentor voice" detail="Enable spoken responses when audio is available."><label className="setting-toggle"><input type="checkbox" checked={audio.voiceOutput} onChange={event => changeAudio({ voiceOutput: event.target.checked })} /><span>Voice output</span></label></SettingRow>
    <SettingRow title="Automatic playback" detail="Read new coach responses automatically when voice output is enabled."><label className="setting-toggle"><input type="checkbox" checked={audio.autoSpeak} onChange={event => changeAudio({ autoSpeak: event.target.checked })} /><span>Automatically read responses</span></label></SettingRow>
    <SettingRow title="Session introductions" detail="Play a welcome at the beginning of a new session."><label className="setting-toggle"><input type="checkbox" checked={audio.introductions} onChange={event => changeAudio({ introductions: event.target.checked })} /><span>Play introductions</span></label></SettingRow>
    <SettingRow title="Volume" detail="Adjust mentor playback. This does not change your microphone."><label className="setting-range">Playback volume<input type="range" aria-label="Playback volume" aria-valuetext={`${Math.round(audio.volume * 100)} percent`} min="0" max="1" step="0.05" value={audio.volume} onChange={event => changeAudio({ volume: Number(event.target.value) })} /><span aria-hidden="true">{Math.round(audio.volume * 100)}%</span></label></SettingRow>
    <SettingRow title="Mute playback" detail="Silence audio without changing your preferred volume."><label className="setting-toggle"><input type="checkbox" checked={audio.muted} onChange={event => changeAudio({ muted: event.target.checked })} /><span>Mute audio</span></label></SettingRow>
    <SettingRow title="Playback speed" detail="Choose a comfortable pace for listening."><label>Playback speed<select value={audio.speed} onChange={event => changeAudio({ speed: Number(event.target.value) })}>{[0.5, 0.75, 1, 1.25, 1.5, 1.75, 2].map(speed => <option key={speed} value={speed}>{speed}×{speed === 1 ? ' — Normal' : ''}</option>)}</select></label></SettingRow>
    <SettingRow title="Voice" detail="Provider-documented voices. Availability depends on the configured speech service."><label>Spoken voice<select value={speech.voice} onChange={event => { if (isTTSVoice(event.target.value)) changeSpeech({ voice: event.target.value }); }}>{TTS_VOICES.map(voice => <option key={voice}>{voice}</option>)}</select></label></SettingRow>
    <MicrophoneCheck />
    <p className="settings-footnote">Microphone permission is requested only when you choose to speak in a session or explicitly check the microphone here. You can always type instead.</p>
  </>;
  else if (category.id === 'interview') content = <InterviewDefaults onSaved={ok => { setError(null); setNotice(ok ? 'Saved on this device' : null); }} />;
  else if (category.id === 'language') content = <>
    <SettingRow title="Speech recognition" detail="The language you use when speaking to your mentor."><label>Recognition language<select value={speech.sttLanguage} onChange={event => { if (isSpeechLocale(event.target.value)) changeSpeech({ sttLanguage: event.target.value }); }}>{SPEECH_LANGUAGES.map(item => <option key={item.code} value={item.code}>{languageLabel(item.code, item.label)}</option>)}</select></label></SettingRow>
    <SettingRow title="Spoken responses" detail="The language used for your mentor’s audio replies."><label>Spoken response language<select value={speech.spokenLanguage} onChange={event => { if (isSpeechLocale(event.target.value)) changeSpeech({ spokenLanguage: event.target.value }); }}>{SPEECH_LANGUAGES.map(item => <option key={item.code} value={item.code}>{languageLabel(item.code, item.label)}</option>)}</select></label></SettingRow>
    <SettingRow title="A little English, too" detail="Code mixing is supported for Tamil, Hindi, and Bengali with English."><label className="setting-toggle"><input type="checkbox" checked={speech.codeMixing} disabled={!CODE_MIXING_LANGUAGES.includes(speech.sttLanguage)} onChange={event => changeSpeech({ codeMixing: event.target.checked })} /><span>Mix with English</span></label></SettingRow>
    <div className="settings-limitation"><h3>Interface language</h3><p>The interface is currently in English. Full interface translation is not available yet; speech language changes do not translate menus.</p><p>These are provider-documented speech options, not a guarantee of live service availability.</p></div>
  </>;
  else if (category.id === 'appearance') content = <><fieldset className="theme-options"><legend>Color theme</legend>{(['light', 'dark', 'system'] as ThemePreference[]).map(value => <label key={value} className={`theme-option theme-${value}`}><input type="radio" aria-label={value[0].toUpperCase() + value.slice(1)} name="theme" value={value} checked={theme === value} onChange={() => changeTheme(value)} /><span className="theme-preview" aria-hidden="true"><i /><i /><i /></span><strong>{value[0].toUpperCase() + value.slice(1)}</strong><small>{value === 'system' ? 'Follow your device' : value === 'dark' ? 'A quieter evening workspace' : 'Warm, bright, and focused'}</small></label>)}</fieldset><p className="settings-footnote">Text size and reduced motion follow your browser and device accessibility settings.</p></>;
  else if (category.id === 'learning') content = <div className="settings-limitation"><Icon name="compass" /><h3>Your curriculum is ready when you are</h3><p>Study goals and reminders are not available yet. Lessons follow their published prerequisites, and progress updates after recorded practice.</p><a href="/learn" className="product-button">Open curriculum <Icon name="arrow" /></a></div>;
  else if (category.id === 'privacy') content = <div className="settings-privacy"><section><h3>On this device</h3><p>Audio and language preferences, microphone selection, interview defaults, appearance, DSA drafts, and bookmarks are stored in this browser. Microphone permission is not a saved preference. Local microphone checks discard their audio and retain only temporary signal diagnostics on screen.</p></section><section><h3>In this tab’s workspace</h3><p>Your workspace capability and practice session references stay in tab-scoped storage. The server records lesson answers and learning activity associated with that workspace.</p></section><WorkspaceRecovery /><section><h3>You choose when to share</h3><p>Microphone access starts only after an explicit speech action. Interview camera preview is optional. Server data deletion is available through the workspace controls in Design studio; resetting preferences here does not delete learning records.</p><a href="/studio">Open workspace controls</a></section></div>;
  else content = <div className="settings-limitation"><h3>A fresh set of preferences</h3><p>Restore audio, speech, microphone selection, interview, appearance, and workspace layout defaults. This will not delete drafts, bookmarks, lesson progress, or workspace credentials.</p>{confirmReset ? <div className="settings-reset-confirm" role="group" aria-label="Confirm preference reset"><p>Reset your preferences to their defaults?</p><button ref={confirm} type="button" onClick={resetPreferences}>Confirm reset</button><button type="button" onClick={() => setConfirmReset(false)}>Cancel</button></div> : <button type="button" onClick={() => setConfirmReset(true)}>Reset preferences</button>}</div>;
  return <>
    <header className="product-page-heading"><p>Your workspace, your way</p><h1>Settings</h1><span>A few thoughtful adjustments for a better conversation.</span></header>
    <div className="settings-layout"><nav className="settings-categories" aria-label="Settings categories">{categories.map((item, index) => <a id={`settings-${item.id}`} key={item.id} href={`/settings?category=${item.id}`} aria-current={category.id === item.id ? 'page' : undefined} onKeyDown={event => categoryKey(event, index)}><Icon name={item.icon} /><span>{item.title}</span></a>)}</nav><section className="settings-panel" aria-labelledby="settings-category-title"><header><p className="learning-eyebrow">Preferences</p><h2 id="settings-category-title">{category.title}</h2><p>{category.description}</p></header>{error && <p className="learning-notice" role="alert">{error}</p>}{notice && <p className="settings-save-status" role="status">{notice}</p>}{content}</section></div>
  </>;
}
