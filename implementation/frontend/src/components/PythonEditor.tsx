import { useEffect, useRef, useState } from 'react';
import Editor, { loader, type OnMount } from '@monaco-editor/react';
import * as monaco from 'monaco-editor/editor/editor.api.js';
import 'monaco-editor/languages/definitions/python/register.js';
import EditorWorker from 'monaco-editor/editor/editor.worker.js?worker';

// Bundle workers locally: no CDN request or learner source upload is needed.
self.MonacoEnvironment = { getWorker: () => new EditorWorker() };
loader.config({ monaco });

export function PythonEditor({ value, onChange, highlightedLine }: { value: string; onChange: (value: string) => void; highlightedLine: number | null }): React.ReactElement {
  const [plain, setPlain] = useState(false);
  // Horizon keeps its coding surface dark in either application theme.
  const theme = 'vs-dark';
  const instance = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const decorations = useRef<monaco.editor.IEditorDecorationsCollection | null>(null);
  const mount: OnMount = editor => { instance.current = editor; decorations.current = editor.createDecorationsCollection(); };
  useEffect(() => {
    decorations.current?.set(highlightedLine ? [{ range: new monaco.Range(highlightedLine, 1, highlightedLine, 1), options: { isWholeLine: true, className: 'active-trace-line' } }] : []);
    if (highlightedLine) instance.current?.revealLineInCenterIfOutsideViewport(highlightedLine);
  }, [highlightedLine]);
  return <div className="editor-container">
    <button type="button" aria-pressed={plain} onClick={() => setPlain(p => !p)}>{plain ? 'Use Monaco Editor' : 'Use Accessible Plain Text Editor'}</button>
    {plain ? <textarea aria-label="Python Solution Editor" value={value} onChange={e => onChange(e.target.value)} rows={14} style={{ width: '100%', fontFamily: 'monospace' }} /> : <Editor height="100%" theme={theme} language="python" value={value} onChange={next => onChange(next ?? '')} onMount={mount} options={{ ariaLabel: 'Python Solution Editor', minimap: { enabled: false }, fontSize: 14, fontFamily: 'JetBrains Mono, monospace', automaticLayout: true, scrollBeyondLastLine: false, tabSize: 4, accessibilitySupport: 'on' }} loading={<p role="status">Loading code editor…</p>} />}
  </div>;
}
