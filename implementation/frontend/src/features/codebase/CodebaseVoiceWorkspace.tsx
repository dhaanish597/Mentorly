import { useEffect, useRef, useState } from 'react';
import { Icon, MentorPortrait } from '../../components/HorizonVisuals';
import type { Workspace } from '../../studioApi';
import {
  submitTextTurn,
  type Citation,
  type CodebaseMessage,
  type CodebaseSession,
  type TurnResult,
} from './codebaseApi';
import { useCodebaseVoice } from './useCodebaseVoice';

export type CodebaseVoiceWorkspaceProps = {
  workspace: Workspace;
  session: CodebaseSession;
  onSessionUpdated: (session: CodebaseSession) => void;
  onBackToHistory: () => void;
  onNewSession: () => void;
};

export function CodebaseVoiceWorkspace({
  workspace,
  session,
  onSessionUpdated,
  onBackToHistory,
  onNewSession,
}: CodebaseVoiceWorkspaceProps) {
  const [messages, setMessages] = useState<CodebaseMessage[]>(session.messages ?? []);
  const [typedText, setTypedText] = useState('');
  const [isSubmittingText, setIsSubmittingText] = useState(false);
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null);
  const [activeTopic, setActiveTopic] = useState(session.current_topic);
  const [knowledgeLevel, setKnowledgeLevel] = useState(session.knowledge_level);
  const [voiceMuted, setVoiceMuted] = useState(false);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);

  const transcriptEndRef = useRef<HTMLDivElement | null>(null);
  const transcriptContainerRef = useRef<HTMLDivElement | null>(null);
  const userScrolledRef = useRef(false);

  // Initial mentor audio from message 1 if available
  const initialAudio = session.messages?.[0]?.audio_url;

  function handleTurnComplete(turnResult: TurnResult) {
    if (!turnResult?.learner_message || !turnResult?.mentor_message) return;
    setMessages((prev) => [
      ...prev,
      turnResult.learner_message,
      turnResult.mentor_message,
    ]);
    if (turnResult.current_topic) setActiveTopic(turnResult.current_topic);
    if (turnResult.knowledge_level) setKnowledgeLevel(turnResult.knowledge_level);
    setErrorBanner(null);
    onSessionUpdated({
      ...session,
      current_topic: turnResult.current_topic || session.current_topic,
      knowledge_level: turnResult.knowledge_level || session.knowledge_level,
      messages: [...messages, turnResult.learner_message, turnResult.mentor_message],
    });
  }

  const {
    voiceState,
    isRecording,
    activeAudioUrl,
    liveTranscript,
    audioUnlocked,
    initializeVoice,
    startListening,
    stopAndSubmit,
    stopVoice,
    playAudioUrl,
  } = useCodebaseVoice({
    workspace,
    sessionId: session.session_id,
    initialAudioUrl: initialAudio,
    onTurnComplete: handleTurnComplete,
    onError: (msg) => setErrorBanner(msg),
    enabled: !voiceMuted,
  });

  // Automatically start / initialize on mount
  useEffect(() => {
    if (!audioUnlocked && !voiceMuted) {
      void initializeVoice();
    }
  }, [audioUnlocked, initializeVoice, voiceMuted]);

  // Keep messages in sync if session prop changes
  useEffect(() => {
    if (session.messages) {
      setMessages(session.messages);
    }
  }, [session.messages]);

  // Handle user scroll detection
  function handleScroll() {
    const el = transcriptContainerRef.current;
    if (!el) return;
    const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50;
    userScrolledRef.current = !isAtBottom;
  }

  // Ensure the page window remains at the top on mount
  useEffect(() => {
    const isJsdom = typeof navigator !== 'undefined' && /jsdom/i.test(navigator.userAgent);
    if (!isJsdom && typeof window !== 'undefined' && typeof window.scrollTo === 'function') {
      try {
        window.scrollTo(0, 0);
      } catch {
        // ignore in mock environments
      }
    }
    const el = transcriptContainerRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, []);

  // Auto-scroll ONLY the internal transcript container, NEVER the window or outer layout
  useEffect(() => {
    if (!userScrolledRef.current && transcriptContainerRef.current) {
      const el = transcriptContainerRef.current;
      if (typeof el.scrollTo === 'function') {
        try {
          el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
          return;
        } catch {
          // fallback to scrollTop
        }
      }
      el.scrollTop = el.scrollHeight;
    }
  }, [messages, liveTranscript, voiceState]);

  async function handleSendText() {
    const text = typedText.trim();
    if (!text || isSubmittingText) return;

    setIsSubmittingText(true);
    setTypedText('');
    setErrorBanner(null);

    // Stop current voice capture while text is processing
    stopVoice();

    try {
      const turnResult = await submitTextTurn(workspace, session.session_id, text);
      handleTurnComplete(turnResult);

      // Play mentor audio if returned and voice isn't muted
      if (turnResult.mentor_message.audio_url && !voiceMuted) {
        void playAudioUrl(turnResult.mentor_message.audio_url);
      } else {
        void startListening();
      }
    } catch (err) {
      setErrorBanner(err instanceof Error ? err.message : 'Failed to send message.');
      void startListening();
    } finally {
      setIsSubmittingText(false);
    }
  }

  const latestMentorMessage = [...messages].reverse().find((m) => m && m.role === 'mentor');

  return (
    <div className="codebase-workspace">
      {/* Top Session Bar */}
      <header className="workspace-top-bar">
        <div className="bar-left">
          <button type="button" className="ghost-button" onClick={onBackToHistory}>
            ← All sessions
          </button>
          <div className="bar-repo-info">
            <span className="repo-pill">
              <Icon name="code" /> {session.repo_name}
            </span>
            <span className="branch-tag">{session.branch || 'main'}</span>
            <span className="title-tag">{session.title}</span>
          </div>
        </div>

        <div className="bar-actions">
          <button
            type="button"
            className={`voice-toggle-btn ${voiceMuted ? 'muted' : 'active'}`}
            onClick={() => {
              if (voiceMuted) {
                setVoiceMuted(false);
                void initializeVoice();
              } else {
                setVoiceMuted(true);
                stopVoice();
              }
            }}
            title={voiceMuted ? 'Turn on hands-free voice' : 'Mute hands-free voice'}
          >
            {voiceMuted ? '🔇 Voice muted' : '🎙️ Hands-free active'}
          </button>
          <button type="button" className="ghost-button" onClick={onNewSession}>
            + New session
          </button>
        </div>
      </header>

      {errorBanner && (
        <div className="codebase-alert banner" role="alert">
          <Icon name="warning" />
          <span>{errorBanner}</span>
          <button type="button" className="dismiss-btn" onClick={() => setErrorBanner(null)}>
            ×
          </button>
        </div>
      )}

      {/* Two Column Layout */}
      <div className="workspace-columns">
        {/* LEFT COLUMN: AI Mentor */}
        <aside className="mentor-column" aria-label="AI Mentor">
          <div className="mentor-card">
            <div className={`mentor-avatar-wrap state-${voiceState.toLowerCase()} ${isRecording ? 'recording-active' : ''}`}>
              <MentorPortrait eager />
              <div className="state-ripple" />
            </div>

            <div className="mentor-meta">
              <h3>Nexus</h3>
              <p className="mentor-title">Principal Architecture Mentor</p>
              <div className="mentor-badge-strip">
                <span className="badge topic">Topic: {activeTopic}</span>
                <span className="badge level">Level: {knowledgeLevel}</span>
              </div>
            </div>

            {/* Interactive Voice Action Bar in Left Column */}
            <div className="mentor-voice-action-area">
              {voiceState === 'SPEAKING' && (
                <button
                  type="button"
                  className="voice-action-pill speaking"
                  onClick={stopVoice}
                  title="Click to interrupt mentor and speak"
                >
                  <span className="state-dot speaking" />
                  <span>Nexus speaking · Tap to pause</span>
                </button>
              )}
              {voiceState === 'LISTENING' && (
                <button
                  type="button"
                  className="voice-action-pill listening"
                  onClick={() => void stopAndSubmit()}
                  title="Click to submit your spoken message"
                >
                  <span className="state-dot listening" />
                  <span>Listening to you · Tap to send</span>
                </button>
              )}
              {voiceState === 'PROCESSING' && (
                <div className="voice-action-pill processing">
                  <span className="state-dot processing" />
                  <span>Transcribing speech…</span>
                </div>
              )}
              {voiceState === 'PERMISSION_REQUIRED' && (
                <button
                  type="button"
                  className="voice-action-pill permission"
                  onClick={() => void initializeVoice()}
                  title="Click to enable audio and microphone"
                >
                  <span className="state-dot error" />
                  <span>Click to enable audio & mic</span>
                </button>
              )}
              {voiceState === 'IDLE' && (
                <button
                  type="button"
                  className="voice-action-pill idle"
                  onClick={() => void startListening()}
                  title="Click to start speaking"
                >
                  <span className="state-dot idle" />
                  <span>Tap to speak with Nexus</span>
                </button>
              )}
              {voiceState === 'INITIALIZING' && (
                <div className="voice-action-pill init">
                  <span className="state-dot init" />
                  <span>Connecting voice…</span>
                </div>
              )}
            </div>

            {/* Current Mentor Thought / Focus Question */}
            <div className="current-focus-card">
              <span className="focus-label">Current discussion</span>
              <p className="focus-text">
                {latestMentorMessage?.content || 'Exploring repository architecture and design tradeoffs.'}
              </p>
            </div>

            {/* Citation Inspector Preview */}
            {selectedCitation && (
              <div className="citation-preview-card">
                <div className="citation-header">
                  <span className="cit-file">{selectedCitation.path}</span>
                  <button type="button" className="close-cit" onClick={() => setSelectedCitation(null)}>
                    ×
                  </button>
                </div>
                <div className="citation-lines">
                  Lines {selectedCitation.start_line}–{selectedCitation.end_line}
                  {selectedCitation.symbol && ` · ${selectedCitation.symbol}`}
                </div>
                {selectedCitation.excerpt && (
                  <pre className="citation-snippet">
                    <code>{selectedCitation.excerpt}</code>
                  </pre>
                )}
              </div>
            )}
          </div>
        </aside>

        {/* RIGHT COLUMN: Conversation Transcript */}
        <main className="transcript-column" aria-label="Conversation transcript">
          <div
            className="transcript-scroll"
            ref={transcriptContainerRef}
            onScroll={handleScroll}
          >
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={`transcript-message role-${msg.role}`}
              >
                <div className="message-header">
                  <span className="message-author">
                    {msg.role === 'mentor' ? 'Nexus' : 'You'}
                  </span>
                  <span className="message-time">
                    {new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>

                <div className="message-bubble">
                  <p>{msg.content}</p>

                  {/* Audio Replay Button for Mentor Messages */}
                  {msg.role === 'mentor' && msg.audio_url && (
                    <div className="message-audio-controls">
                      <button
                        type="button"
                        className={`audio-replay-btn ${activeAudioUrl === msg.audio_url ? 'playing' : ''}`}
                        onClick={() => {
                          if (activeAudioUrl === msg.audio_url) {
                            stopVoice();
                          } else {
                            void playAudioUrl(msg.audio_url!);
                          }
                        }}
                        title={activeAudioUrl === msg.audio_url ? 'Pause audio' : 'Play mentor speech'}
                      >
                        <Icon name={activeAudioUrl === msg.audio_url ? 'pause' : 'volume'} />
                        <span>{activeAudioUrl === msg.audio_url ? 'Pause voice' : 'Play voice'}</span>
                      </button>
                    </div>
                  )}

                  {/* Render citations if attached */}
                  {msg.citations && msg.citations.length > 0 && (
                    <div className="message-citations">
                      <span className="citations-label">References:</span>
                      {msg.citations.map((cit, idx) => (
                        <button
                          key={`${cit.path}_${cit.start_line}_${idx}`}
                          type="button"
                          className="citation-tag"
                          onClick={() => setSelectedCitation(cit)}
                          title={`Inspect ${cit.path}`}
                        >
                          <Icon name="code" /> {cit.path}:{cit.start_line}–{cit.end_line}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}

            {/* Live speech recognition transcription indicator */}
            {voiceState === 'LISTENING' && (
              <div className="transcript-message role-learner live-preview">
                <div className="message-bubble listening-bubble">
                  <span className="listening-pulse-dot" />
                  <span className="pulse-dots">Listening to your voice… Speak naturally</span>
                </div>
              </div>
            )}

            {voiceState === 'PROCESSING' && (
              <div className="transcript-message role-mentor live-preview">
                <div className="message-bubble processing-bubble">
                  <span className="pulse-dots">Transcribing speech with Gnani STT…</span>
                </div>
              </div>
            )}

            <div ref={transcriptEndRef} />
          </div>

          {/* Bottom Composer (Voice Mic + Text Fallback) */}
          <footer className="transcript-footer">
            {voiceState === 'LISTENING' && (
              <div className="listening-banner-bar">
                <span className="rec-dot-animated" />
                <span className="rec-instruction">
                  Microphone is active. Speak now, or click <strong>Done speaking</strong> to send.
                </span>
              </div>
            )}

            <form
              className="composer-form"
              onSubmit={(e) => {
                e.preventDefault();
                void handleSendText();
              }}
            >
              <input
                type="text"
                placeholder={
                  voiceState === 'LISTENING'
                    ? 'Listening… speak naturally, or type here'
                    : 'Type a message to your mentor…'
                }
                value={typedText}
                onChange={(e) => setTypedText(e.target.value)}
                disabled={isSubmittingText}
              />

              {/* Dynamic Mic / Speak Action Button */}
              {voiceState === 'LISTENING' ? (
                <button
                  type="button"
                  className="voice-control-btn active-rec"
                  onClick={() => void stopAndSubmit()}
                  title="Finish speaking and submit your answer"
                >
                  <span className="rec-square-icon" />
                  <span>Done speaking</span>
                </button>
              ) : voiceState === 'PROCESSING' ? (
                <button
                  type="button"
                  className="voice-control-btn processing"
                  disabled
                  title="Processing speech"
                >
                  <span className="spin-icon" />
                  <span>Transcribing…</span>
                </button>
              ) : voiceState === 'SPEAKING' ? (
                <button
                  type="button"
                  className="voice-control-btn speaking"
                  onClick={stopVoice}
                  title="Interrupt mentor speech"
                >
                  <Icon name="pause" />
                  <span>Interrupt</span>
                </button>
              ) : (
                <button
                  type="button"
                  className="voice-control-btn idle"
                  onClick={() => void startListening()}
                  title="Start speaking to your mentor"
                >
                  <Icon name="mic" />
                  <span>Speak</span>
                </button>
              )}

              {/* Send Text Button */}
              <button
                type="submit"
                className="send-button primary"
                disabled={!typedText.trim() || isSubmittingText}
              >
                {isSubmittingText ? 'Sending…' : 'Send'}
              </button>
            </form>
          </footer>
        </main>
      </div>
    </div>
  );
}
