import '@testing-library/jest-dom/vitest';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { CodebaseOnboarding } from '../features/codebase/CodebaseOnboarding';
import { CodebaseSessionHistory } from '../features/codebase/CodebaseSessionHistory';
import { CodebaseVoiceWorkspace } from '../features/codebase/CodebaseVoiceWorkspace';
import { CodebaseLearningView } from '../features/codebase/CodebaseLearningView';
import type { CodebaseSession } from '../features/codebase/codebaseApi';
import type { Workspace } from '../studioApi';

// Mock audio recorder and player
vi.mock('../services/audioRecorder', () => ({
  AudioRecorder: class {
    startMicrophoneCapture = vi.fn().mockResolvedValue(true);
    stopMicrophoneCapture = vi.fn().mockResolvedValue(new ArrayBuffer(1024));
    dispose = vi.fn();
  },
}));

vi.mock('../services/audioPlayer', () => ({
  AudioPlayer: class {
    playWavBytes = vi.fn().mockImplementation(({ onEnded }: { onEnded?: () => void }) => {
      onEnded?.();
      return Promise.resolve();
    });
    playPcm = vi.fn().mockResolvedValue(undefined);
    stop = vi.fn();
    bargeInStop = vi.fn();
    isPlaying = vi.fn().mockReturnValue(false);
  },
}));

const mockWorkspace: Workspace = { id: 'ws-test-123', token: 'token-secret' };

const sampleSession: CodebaseSession = {
  session_id: 'cls_session_abc123',
  workspace_id: 'ws-test-123',
  repo_id: 'repo-xyz',
  snapshot_id: 'snap-xyz',
  title: 'Exploring FastAPI Architecture',
  knowledge_level: 'intermediate',
  status: 'active',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  repo_url: 'https://github.com/tiangolo/fastapi',
  repo_name: 'tiangolo/fastapi',
  messages: [
    {
      id: 'msg-1',
      session_id: 'cls_session_abc123',
      role: 'mentor',
      content: 'Welcome! How familiar are you with FastAPI and ASGI applications?',
      audio_url: '/api/v1/codebase-learning/audio/msg-1.wav',
      focus_topic: 'FastAPI Framework',
      focus_question: 'How familiar are you with FastAPI and ASGI applications?',
      citations: [
        {
          path: 'fastapi/applications.py',
          symbol: 'FastAPI',
          start_line: 45,
          end_line: 90,
          text: 'class FastAPI(Starlette):\n    def __init__(...): pass',
        },
      ],
      created_at: new Date().toISOString(),
    },
  ],
};

const yesterdaySession: CodebaseSession = {
  session_id: 'cls_session_yesterday',
  workspace_id: 'ws-test-123',
  repo_id: 'repo-zustand',
  snapshot_id: 'snap-zustand',
  title: 'State Management with Zustand',
  knowledge_level: 'beginner',
  status: 'active',
  created_at: new Date(Date.now() - 28 * 3600 * 1000).toISOString(),
  updated_at: new Date(Date.now() - 28 * 3600 * 1000).toISOString(),
  repo_url: 'https://github.com/pmndrs/zustand',
  repo_name: 'pmndrs/zustand',
  messages: [],
};

const olderSession: CodebaseSession = {
  session_id: 'cls_session_older',
  workspace_id: 'ws-test-123',
  repo_id: 'repo-flask',
  snapshot_id: 'snap-flask',
  title: 'Understanding WSGI Dispatch in Flask',
  knowledge_level: 'advanced',
  status: 'active',
  created_at: new Date(Date.now() - 5 * 24 * 3600 * 1000).toISOString(),
  updated_at: new Date(Date.now() - 5 * 24 * 3600 * 1000).toISOString(),
  repo_url: 'https://github.com/pallets/flask',
  repo_name: 'pallets/flask',
  messages: [],
};

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.restoreAllMocks();
});

describe('CodebaseOnboarding Component', () => {
  it('renders clean onboarding interface matching product specs', () => {
    render(
      <CodebaseOnboarding
        workspace={mockWorkspace}
        onSessionReady={vi.fn()}
      />
    );

    expect(screen.getByText('Learn any GitHub repository with your AI mentor.')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Paste a repository URL. Your mentor will help you understand the architecture, code, and design decisions through conversation.'
      )
    ).toBeInTheDocument();

    const input = screen.getByPlaceholderText('https://github.com/owner/repository');
    expect(input).toBeInTheDocument();

    expect(screen.getByRole('button', { name: /Start learning/i })).toBeInTheDocument();
    expect(screen.getByText(/microphone permission/i)).toBeInTheDocument();
  });

  it('clicking example repository triggers start learning', async () => {
    const onSessionReady = vi.fn();
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url);
      if (u.includes('/repos/ingest') && init?.method === 'POST') {
        return new Response(JSON.stringify({ repo_id: 'r1', snapshot_id: 's1', status: 'READY', files_indexed: 50, total_files: 50, coverage_ratio: 1.0 }), { status: 200 });
      }
      if (u.includes('/codebase-learning/sessions') && init?.method === 'POST') {
        return new Response(JSON.stringify(sampleSession), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchSpy);

    render(
      <CodebaseOnboarding
        workspace={mockWorkspace}
        onSessionReady={onSessionReady}
      />
    );

    const fastapiBtn = screen.getByRole('button', { name: /FastAPI \(Python\)/i });
    fireEvent.click(fastapiBtn);

    await waitFor(() => {
      expect(onSessionReady).toHaveBeenCalledWith(expect.objectContaining({ session_id: 'cls_session_abc123' }));
    });
  });

  it('validates invalid GitHub URL on submit', async () => {
    render(
      <CodebaseOnboarding
        workspace={mockWorkspace}
        onSessionReady={vi.fn()}
      />
    );

    const input = screen.getByPlaceholderText('https://github.com/owner/repository');
    fireEvent.change(input, { target: { value: 'not-a-valid-url' } });

    fireEvent.click(screen.getByRole('button', { name: /Start learning/i }));

    await screen.findByText(/Please provide a valid GitHub repository URL/i);
  });

  it('reuses the snapshot and idempotency key after a lost creation response', async () => {
    const attempts: { key: string; snapshot: string }[] = [];
    let ingests = 0;
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).includes('/repos/ingest')) {
        ingests++;
        return new Response(JSON.stringify({ snapshot_id: 's1', status: 'READY' }), { status: 200 });
      }
      if (String(url).includes('/codebase-learning/sessions')) {
        const headers = init?.headers as Record<string, string>;
        expect(headers['Idempotency-Key']).toBe(headers['X-Idempotency-Key']);
        attempts.push({ key: headers['Idempotency-Key'], snapshot: JSON.parse(String(init?.body)).snapshot_id });
        if (attempts.length === 1) throw new Error('Response lost');
        return new Response(JSON.stringify({ detail: 'Session creation already admitted' }), { status: 409 });
      }
      throw new Error('Unexpected request');
    }));
    const view = render(<CodebaseOnboarding workspace={mockWorkspace} onSessionReady={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText('https://github.com/owner/repository'), { target: { value: 'https://github.com/tiangolo/fastapi' } });
    fireEvent.click(screen.getByRole('button', { name: /Start learning/i }));
    await screen.findByText('Response lost');
    expect(sessionStorage.getItem('viva-codebase-pending-v1')).not.toContain(mockWorkspace.token);
    view.unmount();
    render(<CodebaseOnboarding workspace={mockWorkspace} onSessionReady={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText('https://github.com/owner/repository'), { target: { value: 'https://github.com/tiangolo/fastapi' } });
    fireEvent.click(screen.getByRole('button', { name: /Start learning/i }));
    await waitFor(() => expect(attempts).toHaveLength(2));
    expect(ingests).toBe(1);
    expect(attempts[0]).toEqual(attempts[1]);
    expect(attempts[0].snapshot).toBe('s1');
    expect(attempts[0].key).toBeTruthy();
  });

  it('ignores a session response after the workspace changes', async () => {
    let resolveCreate!: (value: Response) => void;
    const createResponse = new Promise<Response>((resolve) => { resolveCreate = resolve; });
    const onSessionReady = vi.fn();
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (String(url).includes('/repos/ingest')) return new Response(JSON.stringify({ snapshot_id: 'rotate-snapshot', status: 'READY' }), { status: 200 });
      return createResponse;
    }));
    const view = render(<CodebaseOnboarding workspace={mockWorkspace} onSessionReady={onSessionReady} />);
    fireEvent.change(screen.getByPlaceholderText('https://github.com/owner/repository'), { target: { value: 'https://github.com/example/rotate' } });
    fireEvent.click(screen.getByRole('button', { name: /Start learning/i }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    view.rerender(<CodebaseOnboarding workspace={{ id: 'other', token: 'other-token' }} onSessionReady={onSessionReady} />);
    await act(async () => { resolveCreate(new Response(JSON.stringify(sampleSession), { status: 200 })); await createResponse; });
    expect(onSessionReady).not.toHaveBeenCalled();
  });

  it('does not let an older completion clear a newer attempt for the same repository', async () => {
    let resolveFirst!: (response: Response) => void;
    const firstResponse = new Promise<Response>((resolve) => { resolveFirst = resolve; });
    let creations = 0;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (String(url).includes('/repos/ingest')) return new Response(JSON.stringify({ snapshot_id: 's1', status: 'READY' }), { status: 200 });
      creations++;
      if (creations === 1) return firstResponse;
      throw new Error('Response lost');
    }));
    render(<CodebaseOnboarding workspace={mockWorkspace} onSessionReady={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText('https://github.com/owner/repository'), { target: { value: 'https://github.com/example/repo' } });
    fireEvent.click(screen.getByRole('button', { name: /Start learning/i }));
    await waitFor(() => expect(creations).toBe(1));
    // Another attempt replaced the original record while its response was in flight.
    const stored = JSON.parse(sessionStorage.getItem('viva-codebase-pending-v1')!);
    sessionStorage.setItem('viva-codebase-pending-v1', JSON.stringify({ ...stored, key: 'newer-attempt' }));
    const newer = sessionStorage.getItem('viva-codebase-pending-v1');
    await act(async () => { resolveFirst(new Response(JSON.stringify(sampleSession), { status: 200 })); await firstResponse; });
    expect(sessionStorage.getItem('viva-codebase-pending-v1')).toBe(newer);
  });

  it('orchestrates ingestion and session creation on valid URL', async () => {
    const onSessionReady = vi.fn();
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url);
      if (u.includes('/repos/ingest') && init?.method === 'POST') {
        return new Response(JSON.stringify({ repo_id: 'r1', snapshot_id: 's1', status: 'READY', files_indexed: 50, total_files: 50, coverage_ratio: 1.0 }), { status: 200 });
      }
      if (u.includes('/codebase-learning/sessions') && init?.method === 'POST') {
        return new Response(JSON.stringify(sampleSession), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchSpy);

    render(
      <CodebaseOnboarding
        workspace={mockWorkspace}
        onSessionReady={onSessionReady}
      />
    );

    const input = screen.getByPlaceholderText('https://github.com/owner/repository');
    fireEvent.change(input, { target: { value: 'https://github.com/tiangolo/fastapi' } });

    fireEvent.click(screen.getByRole('button', { name: /Start learning/i }));

    await waitFor(() => {
      expect(onSessionReady).toHaveBeenCalledWith(expect.objectContaining({ session_id: 'cls_session_abc123' }));
    });
  });
});

describe('CodebaseSessionHistory Component', () => {
  const sessions = [sampleSession, yesterdaySession, olderSession];

  it('renders saved conversations grouped by Today, Yesterday, and Previous', () => {
    render(
      <CodebaseSessionHistory
        workspace={mockWorkspace}
        sessions={sessions}
        onSelectSession={vi.fn()}
        onNewSession={vi.fn()}
        onRefresh={vi.fn()}
      />
    );

    expect(screen.getByText('Your learning sessions')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Today' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Yesterday' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Previous' })).toBeInTheDocument();

    expect(screen.getByText('Exploring FastAPI Architecture')).toBeInTheDocument();
    expect(screen.getByText('State Management with Zustand')).toBeInTheDocument();
    expect(screen.getByText('Understanding WSGI Dispatch in Flask')).toBeInTheDocument();
  });

  it('filters sessions by search term', () => {
    render(
      <CodebaseSessionHistory
        workspace={mockWorkspace}
        sessions={sessions}
        onSelectSession={vi.fn()}
        onNewSession={vi.fn()}
        onRefresh={vi.fn()}
      />
    );

    const searchInput = screen.getByPlaceholderText(/Search learning sessions/i);
    fireEvent.change(searchInput, { target: { value: 'Zustand' } });

    expect(screen.getByText('State Management with Zustand')).toBeInTheDocument();
    expect(screen.queryByText('Exploring FastAPI Architecture')).not.toBeInTheDocument();
  });

  it('handles session renaming', async () => {
    const onRefresh = vi.fn();
    const fetchSpy = vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'PATCH') {
        return new Response(JSON.stringify({ ...sampleSession, title: 'Renamed FastAPI Architecture' }), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchSpy);

    render(
      <CodebaseSessionHistory
        workspace={mockWorkspace}
        sessions={sessions}
        onSelectSession={vi.fn()}
        onNewSession={vi.fn()}
        onRefresh={onRefresh}
      />
    );

    const renameButtons = screen.getAllByRole('button', { name: /Rename session/i });
    fireEvent.click(renameButtons[0]);

    const titleInput = screen.getByDisplayValue('Exploring FastAPI Architecture');
    fireEvent.change(titleInput, { target: { value: 'Renamed FastAPI Architecture' } });

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining('/codebase-learning/sessions/cls_session_abc123'),
        expect.objectContaining({ method: 'PATCH' })
      );
      expect(onRefresh).toHaveBeenCalled();
    });
  });

  it('requires confirmation before deleting a session', async () => {
    const onRefresh = vi.fn();
    const fetchSpy = vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'DELETE') {
        return new Response(JSON.stringify({ success: true }), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchSpy);

    render(
      <CodebaseSessionHistory
        workspace={mockWorkspace}
        sessions={sessions}
        onSelectSession={vi.fn()}
        onNewSession={vi.fn()}
        onRefresh={onRefresh}
      />
    );

    const deleteButtons = screen.getAllByRole('button', { name: /Delete session/i });
    fireEvent.click(deleteButtons[0]);

    // Should prompt confirmation
    expect(screen.getByText(/Delete this learning session\?/i)).toBeInTheDocument();

    // Confirm
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining('/codebase-learning/sessions/cls_session_abc123'),
        expect.objectContaining({ method: 'DELETE' })
      );
      expect(onRefresh).toHaveBeenCalled();
    });
  });
});

describe('CodebaseVoiceWorkspace Component', () => {
  it('renders 2-column layout with mentor portrait and transcript', () => {
    render(
      <CodebaseVoiceWorkspace
        workspace={mockWorkspace}
        session={sampleSession}
        onSessionUpdated={vi.fn()}
        onBackToHistory={vi.fn()}
        onNewSession={vi.fn()}
      />
    );

    // Left column: mentor card, active topic, focus question
    expect(screen.getByRole('complementary', { name: 'AI Mentor' })).toBeInTheDocument();
    expect(screen.getAllByText('Nexus')[0]).toBeInTheDocument();
    expect(screen.getByText('Current discussion')).toBeInTheDocument();
    expect(screen.getAllByText(/Welcome! How familiar are you with FastAPI and ASGI applications\?/i).length).toBeGreaterThanOrEqual(1);

    // Right column: transcript with mentor message
    expect(screen.getByText(/fastapi\/applications\.py/i)).toBeInTheDocument();

    // Text composer fallback
    expect(screen.getByPlaceholderText(/Type a message to your mentor/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument();
  });

  it('submits text turn and updates conversation', async () => {
    const onSessionUpdated = vi.fn();
    const turnResult = {
      session_id: sampleSession.session_id,
      learner_message: {
        id: 'msg-2',
        session_id: sampleSession.session_id,
        sequence: 2,
        role: 'learner' as const,
        content: 'I have used FastAPI to build basic REST APIs with Pydantic.',
        citations: [],
        created_at: new Date().toISOString(),
      },
      mentor_message: {
        id: 'msg-3',
        session_id: sampleSession.session_id,
        sequence: 3,
        role: 'mentor' as const,
        content: 'Great! In that case, notice how FastAPI inherits from Starlette in applications.py...',
        audio_url: '/api/v1/codebase-learning/audio/msg-3.wav',
        citations: [],
        created_at: new Date().toISOString(),
      },
      current_topic: 'Starlette Inheritance',
      knowledge_level: 'intermediate',
    };

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (init?.method === 'POST' && String(url).includes('/turns')) {
          return new Response(JSON.stringify(turnResult), { status: 200 });
        }
        return new Response(JSON.stringify({}), { status: 200 });
      })
    );

    render(
      <CodebaseVoiceWorkspace
        workspace={mockWorkspace}
        session={sampleSession}
        onSessionUpdated={onSessionUpdated}
        onBackToHistory={vi.fn()}
        onNewSession={vi.fn()}
      />
    );

    const input = screen.getByPlaceholderText(/Type a message to your mentor/i);
    fireEvent.change(input, { target: { value: 'I have used FastAPI to build basic REST APIs with Pydantic.' } });

    fireEvent.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() => {
      expect(onSessionUpdated).toHaveBeenCalledWith(expect.objectContaining({ session_id: 'cls_session_abc123' }));
    });
  });
});

describe('CodebaseLearningView Component', () => {
  it('loads and displays onboarding when no sessions exist', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (String(url).includes('/codebase-learning/sessions')) {
          return new Response(JSON.stringify({ sessions: [] }), { status: 200 });
        }
        return new Response(JSON.stringify({}), { status: 200 });
      })
    );

    render(
      <CodebaseLearningView
        workspace={mockWorkspace}
        ensureWorkspace={async () => mockWorkspace}
        active={true}
      />
    );

    await screen.findByText('Learn any GitHub repository with your AI mentor.');
  });

  it('loads and displays session history when saved sessions exist', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (String(url).includes('/codebase-learning/sessions')) {
          return new Response(JSON.stringify({ sessions: [sampleSession] }), { status: 200 });
        }
        return new Response(JSON.stringify({}), { status: 200 });
      })
    );

    render(
      <CodebaseLearningView
        workspace={mockWorkspace}
        ensureWorkspace={async () => mockWorkspace}
        active={true}
      />
    );

    await screen.findByText('Your learning sessions');
    expect(screen.getByText('Exploring FastAPI Architecture')).toBeInTheDocument();
  });
});
