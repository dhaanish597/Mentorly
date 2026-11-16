"""Shared bounded WAV cache, including retained historical audio reads.

HTTP callers retain session capability checks; private cache reads additionally
fence deleted and expired sessions. No provider calls occur here.
"""
from contextlib import closing
from datetime import datetime

from backend.app.db.migrations import open_connection
from backend.app.speech.audio_utils import (
    AudioValidationError, inspect_and_validate_tts_wav, is_riff_wav, wrap_raw_pcm_as_wav,
)
from backend.app.speech.tts_cache import (
    TTSDiskCache, DEFAULT_CACHE_MAX_BYTES, DEFAULT_CACHE_MAX_AGE_SECONDS,
    DEFAULT_CACHE_MAX_ENTRIES, PUBLIC_GENERIC_CONTENT_VERSION,
)
from backend.app.models.api_schemas import TTSAudioConfig


def database_now(conn) -> float:
    return float(conn.execute("SELECT EXTRACT(EPOCH FROM clock_timestamp()) AS now").fetchone()[0])


class PostgresTTSCache:
    """Same cache contract as disk, with transactional session deletion fencing."""
    compute_cache_key = staticmethod(TTSDiskCache.compute_cache_key)

    def __init__(self, target, *, max_bytes=DEFAULT_CACHE_MAX_BYTES,
                 max_age_seconds=DEFAULT_CACHE_MAX_AGE_SECONDS, max_entries=DEFAULT_CACHE_MAX_ENTRIES):
        if any(type(v) is not int or v <= 0 for v in (max_bytes, max_age_seconds, max_entries)):
            raise ValueError('Cache bounds must be positive integers')
        self.target = target
        self.max_bytes, self.max_age_seconds, self.max_entries = max_bytes, max_age_seconds, max_entries

    @staticmethod
    def _identity(cache_key, scope, session_id):
        if not isinstance(cache_key, str) or not cache_key or len(cache_key) > 128 or '/' in cache_key or '\\' in cache_key:
            raise ValueError('Invalid cache key')
        if scope == 'PUBLIC_GENERIC':
            return 'PUBLIC_GENERIC:' + PUBLIC_GENERIC_CONTENT_VERSION, '', cache_key
        if scope == 'SESSION_SCOPED' and isinstance(session_id, str) and session_id.strip():
            return scope, session_id, cache_key
        raise ValueError('A valid cache scope and session identity are required')

    @staticmethod
    def _session_live(conn, scope, sid, now):
        if scope.startswith('PUBLIC_GENERIC:'):
            return True
        row = conn.execute('SELECT deleted_at,expires_at FROM sessions WHERE id=?', (sid,)).fetchone()
        if not row or row['deleted_at'] is not None:
            return False
        expiry = datetime.fromisoformat(row['expires_at'])
        return expiry.tzinfo is not None and expiry.timestamp() > now

    @staticmethod
    def _has_legacy(conn):
        return conn.execute("SELECT to_regclass('legacy_cloud_audio')").fetchone()[0] is not None

    def get_wav(self, cache_key, *, scope='SESSION_SCOPED', session_id=None, expected_sample_rate_hz=None):
        identity = self._identity(cache_key, scope, session_id)
        with closing(open_connection(self.target)) as conn:
            conn.execute('BEGIN IMMEDIATE')
            now = database_now(conn)
            if not self._session_live(conn, identity[0], identity[1], now):
                return None
            row = conn.execute('SELECT wav,created_at,octet_length(wav) AS size FROM cloud_audio WHERE scope=? AND session_id=? AND cache_key=?', identity).fetchone()
            legacy = False
            if row is None and self._has_legacy(conn):
                row = conn.execute('SELECT wav,created_at,octet_length(wav) AS size FROM legacy_cloud_audio WHERE scope=? AND session_id=? AND cache_key=?', identity).fetchone()
                legacy = row is not None
            if row is None:
                return None
            if not legacy and (row['created_at'] < now - self.max_age_seconds or row['size'] > self.max_bytes):
                conn.execute('DELETE FROM cloud_audio WHERE scope=? AND session_id=? AND cache_key=?', identity)
                conn.commit()
                return None
            data = bytes(row['wav'])
            conn.commit()
        try:
            inspect_and_validate_tts_wav(data, expected_sample_rate_hz=expected_sample_rate_hz)
        except AudioValidationError:
            return None
        return data

    def put_completed_stream(self, cache_key, raw_audio_bytes, *, stream_completed,
                             audio_config=None, scope='SESSION_SCOPED', session_id=None):
        if not stream_completed or not raw_audio_bytes:
            raise ValueError('Cannot cache incomplete or empty audio')
        cfg = audio_config or TTSAudioConfig()
        if cfg.container == 'wav' or is_riff_wav(raw_audio_bytes):
            if not is_riff_wav(raw_audio_bytes):
                raise ValueError('Expected RIFF/WAVE bytes')
            wav = bytes(raw_audio_bytes)
        else:
            wav = wrap_raw_pcm_as_wav(raw_audio_bytes, sample_rate_hz=cfg.sample_rate,
                                     num_channels=cfg.num_channels, sample_width_bytes=cfg.sample_width)
        inspect_and_validate_tts_wav(wav, expected_sample_rate_hz=cfg.sample_rate)
        identity = self._identity(cache_key, scope, session_id)
        if len(wav) > self.max_bytes:
            return wav
        with closing(open_connection(self.target)) as conn:
            conn.execute('BEGIN IMMEDIATE')
            now = database_now(conn)
            if not self._session_live(conn, identity[0], identity[1], now):
                raise ValueError('Private audio session has expired or been deleted')
            conn.execute('INSERT INTO cloud_audio VALUES(?,?,?,?,?) ON CONFLICT(scope,session_id,cache_key) DO UPDATE SET wav=excluded.wav,created_at=excluded.created_at', (*identity, wav, now))
            self._enforce(conn, now)
            conn.commit()
        return wav

    def _enforce(self, conn, now):
        removed = conn.execute('DELETE FROM cloud_audio WHERE created_at<?', (now - self.max_age_seconds,)).rowcount
        rows = conn.execute('SELECT scope,session_id,cache_key,octet_length(wav) AS size FROM cloud_audio ORDER BY created_at,scope,session_id,cache_key').fetchall()
        total, entries = sum(r['size'] for r in rows), len(rows)
        # Preserved historical audio consumes capacity but is never evicted to
        # make room for new synthesis. Session deletion remains authoritative.
        if self._has_legacy(conn):
            retained = conn.execute('SELECT COALESCE(SUM(octet_length(wav)),0),COUNT(*) FROM legacy_cloud_audio').fetchone()
            total += retained[0]
            entries += retained[1]
        for row in rows:
            if total <= self.max_bytes and entries <= self.max_entries:
                break
            conn.execute('DELETE FROM cloud_audio WHERE scope=? AND session_id=? AND cache_key=?', (row['scope'], row['session_id'], row['cache_key']))
            total -= row['size']; entries -= 1; removed += 1
        return removed

    def enforce_limits(self):
        with closing(open_connection(self.target)) as conn:
            conn.execute('BEGIN IMMEDIATE')
            removed = self._enforce(conn, database_now(conn))
            conn.commit()
            return removed

    def evict_session(self, session_id):
        with closing(open_connection(self.target)) as conn:
            conn.execute('BEGIN IMMEDIATE')
            removed = conn.execute("DELETE FROM cloud_audio WHERE scope='SESSION_SCOPED' AND session_id=?", (session_id,)).rowcount
            if self._has_legacy(conn):
                removed += conn.execute("DELETE FROM legacy_cloud_audio WHERE scope='SESSION_SCOPED' AND session_id=?", (session_id,)).rowcount
            conn.commit()
            return removed

    def cleanup_partial_temps(self):
        # PostgreSQL writes are transactional; incomplete streams are never inserted.
        return 0
