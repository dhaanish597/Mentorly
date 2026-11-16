import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.repo_learning.audio_storage import (
    MAX_AUDIO_BYTES, cleanup_expired_audio, get_audio, store_audio,
)


def test_audio_requires_owned_live_link_and_expires():
    db = sqlite3.connect(':memory:')
    db.executescript('''
        CREATE TABLE codebase_learning_sessions (id TEXT PRIMARY KEY, workspace_id TEXT, deleted_at TEXT);
        CREATE TABLE codebase_learning_messages (session_id TEXT, audio_path TEXT);
        CREATE TABLE codebase_learning_audio (id TEXT PRIMARY KEY, session_id TEXT, wav BLOB, created_at TEXT, expires_at TEXT);
        INSERT INTO codebase_learning_sessions VALUES ('s', 'owner', NULL);
    ''')
    url = store_audio(db, 's', b'RIFF-test')
    name = url.rsplit('/', 1)[1]
    assert get_audio(db, 'owner', name) is None
    db.execute('INSERT INTO codebase_learning_messages VALUES (?, ?)', ('s', url))
    assert get_audio(db, 'owner', name) == b'RIFF-test'
    assert get_audio(db, 'other', name) is None
    db.execute("UPDATE codebase_learning_sessions SET deleted_at='deleted'")
    assert get_audio(db, 'owner', name) is None
    db.execute('UPDATE codebase_learning_sessions SET deleted_at=NULL')
    db.execute('UPDATE codebase_learning_audio SET expires_at=?', ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),))
    assert get_audio(db, 'owner', name) is None
    cleanup_expired_audio(db)
    assert db.execute('SELECT count(*) FROM codebase_learning_audio').fetchone()[0] == 0
    with pytest.raises(ValueError):
        store_audio(db, 's', b'')
    with pytest.raises(ValueError):
        store_audio(db, 's', b'x' * (MAX_AUDIO_BYTES + 1))


def test_global_cap_is_enforced(monkeypatch):
    from backend.app.repo_learning import audio_storage
    db = sqlite3.connect(':memory:', isolation_level=None)
    db.execute('CREATE TABLE codebase_learning_audio (id TEXT PRIMARY KEY, session_id TEXT, wav BLOB, created_at TEXT, expires_at TEXT)')
    monkeypatch.setattr(audio_storage, 'MAX_TOTAL_AUDIO_BYTES', 6)
    store_audio(db, 'one', b'1234')
    with pytest.raises(ValueError, match='storage is full'):
        store_audio(db, 'two', b'123')
    assert db.execute('SELECT sum(length(wav)) FROM codebase_learning_audio').fetchone()[0] == 4
