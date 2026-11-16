"""Voice-first AI repository mentor service with grounded Socratic reasoning."""

from __future__ import annotations

from uuid import uuid4

from contextlib import closing
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import re
import sqlite3
import uuid
import wave
from typing import Any

import httpx
from fastapi import HTTPException
from backend.app.repo_learning import provider_dispatch
from backend.app.repo_learning.audio_storage import store_audio

from backend.app.core.config import Settings, get_settings, validated_credential
from backend.app.db.migrations import open_connection
from backend.app.models.api_schemas import STTRequest, TTSRequest
from backend.app.models.enums import LanguageMode
from backend.app.speech.gnani_adapter import GnaniSpeechAdapter
from backend.app.speech.pre_tts_normalizer import to_speakable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}"


def _normalize_wav_to_16k_mono(wav_bytes: bytes) -> bytes:
    """Ensure audio is 16 kHz 16-bit mono linear PCM WAV for Gnani STT."""
    try:
        import audioop

        with wave.open(io.BytesIO(wav_bytes), "rb") as r:
            nchannels = r.getnchannels()
            sampwidth = r.getsampwidth()
            framerate = r.getframerate()
            frames = r.readframes(r.getnframes())

        # If already matching, return directly
        if nchannels == 1 and sampwidth == 2 and framerate == 16000:
            return wav_bytes

        # Convert to 16-bit if needed
        if sampwidth != 2:
            frames = audioop.lin2lin(frames, sampwidth, 2)
            sampwidth = 2

        # Convert to mono if needed
        if nchannels > 1:
            frames = audioop.tomono(frames, sampwidth, 0.5, 0.5)
            nchannels = 1

        # Resample to 16000 Hz if needed
        if framerate != 16000:
            frames, _ = audioop.ratecv(frames, sampwidth, nchannels, framerate, 16000, None)

        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(frames)
        return out.getvalue()
    except Exception:
        return wav_bytes


INITIAL_MENTOR_PROMPT = (
    "Hey! I've finished exploring this repository. Before we dive in, "
    "tell me a little about your experience. How familiar are you with the technologies "
    "used here, and what would you like to understand first?"
)


class CodebaseMentorService:
    """Orchestrates persistent sessions, Socratic reasoning, source retrieval, and Gnani voice."""

    def __init__(self, db_path: str | Path, tts_cache_dir: str | Path | None = None, request=None) -> None:
        self.db_path = db_path
        self.request = request
        self.workspace_id = None
        self.provider_request_key = None
        self.provider_fence_token = None
        self.tts_cache_dir = Path(tts_cache_dir) if tts_cache_dir else Path("./data/tts_cache")


    async def _dispatch(self, session_id, operation, dispatch, settings, *, seconds=0, chars=0, calls=1):
        return await provider_dispatch.run(self.db_path, self.request, self.workspace_id, session_id,
                                           operation, dispatch, seconds=seconds, chars=chars, calls=calls,
                                           request_key=self.provider_request_key, token=self.provider_fence_token)

    def _get_adapter(self, settings: Settings | None = None) -> GnaniSpeechAdapter:
        cfg = settings or get_settings()
        api_key = cfg.gnani_api_key.get_secret_value() if cfg.gnani_api_key else None
        return GnaniSpeechAdapter(api_key=api_key,
                                  stt_endpoint=cfg.gnani_base_url.rstrip('/') + '/stt/v3',
                                  tts_endpoint=cfg.gnani_base_url.rstrip('/') + '/api/v1/tts/sse')

    async def _synthesize_audio(self, session_id: str, text: str, settings: Settings | None = None) -> tuple[str | None, bytes | None]:
        """Synthesize speakable text to WAV audio using Gnani TTS."""
        cfg = settings or get_settings()
        if not validated_credential(cfg.gnani_api_key):
            return None, None
        adapter = self._get_adapter(cfg)
        speakable = to_speakable(text)
        speak_text = "\n".join(speakable) if speakable else text
        req = TTSRequest(session_id=session_id, text=speak_text, language=LanguageMode.EN_IN)
        try:
            res = await self._dispatch(session_id, 'TTS', lambda: adapter.synthesize_tts(req), cfg, chars=sum(len(c) for c in to_speakable(speak_text)), calls=len(to_speakable(speak_text)))
            if res and res.wav_bytes:
                return None, res.wav_bytes
        except HTTPException:
            raise
        except (TimeoutError, httpx.TransportError):
            return None, None
        return None, None

    async def create_session(
        self,
        workspace_id: str,
        snapshot_id: str,
        repo_url: str,
        repo_name: str,
        branch: str = "main",
        commit_sha: str | None = None,
        title: str | None = None,
        settings: Settings | None = None,
    ) -> dict[str, Any]:
        """Create a new codebase learning session bound to a ready snapshot."""
        self.workspace_id = workspace_id
        cfg = settings or get_settings()
        create_key = None
        if validated_credential(cfg.gnani_api_key):
            raw_key = provider_dispatch.idempotency_key(self.request) if self.request is not None else None
            if not raw_key or len(raw_key) > 128:
                raise HTTPException(422, 'Cloud greeting requires an Idempotency-Key')
            create_key = workspace_id + ':CREATE:' + raw_key
        admitted_create = False
        conn = open_connection(self.db_path)
        try:
            # Validate snapshot is ready
            snap = conn.execute(
                "SELECT * FROM repo_snapshots WHERE id=? AND workspace_id=? AND status='READY'",
                (snapshot_id, workspace_id),
            ).fetchone()
            if not snap:
                raise ValueError("Repository snapshot is not ready or does not belong to this workspace.")

            if create_key:
                conn.execute('BEGIN IMMEDIATE')
                if conn.execute('SELECT 1 FROM codebase_provider_requests WHERE id=?', (create_key,)).fetchone():
                    raise HTTPException(409, 'Session creation already admitted; retrieve session history')
            session_id = _id("cls_")
            session_title = title.strip() if title and title.strip() else f"Exploring {repo_name}"
            now_iso = _now()


            msg_id = _id("clm_")
            conn.execute(
                """INSERT INTO codebase_learning_sessions(
                    id, workspace_id, repo_snapshot_id, repo_url, repo_name, branch, commit_sha,
                    title, current_topic, knowledge_level, learning_progress_json, pending_question,
                    state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id, workspace_id, snapshot_id, repo_url, repo_name, branch, commit_sha,
                    session_title, "overview", "undetermined", json.dumps({"covered_topics": ["welcome"]}),
                    "How familiar are you with the technologies used here, and what would you like to understand first?",
                    "active", now_iso, now_iso,
                ),
            )

            audio_url = None
            conn.execute(
                """INSERT INTO codebase_learning_messages(
                    id, session_id, sequence, role, content, audio_path, citations_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    msg_id, session_id, 1, "mentor", INITIAL_MENTOR_PROMPT, audio_url,
                    "[]", json.dumps({"stage": "greeting"}), now_iso,
                ),
            )
            if create_key:
                conn.execute('INSERT INTO codebase_provider_requests VALUES(?,?,?,?,?)', (create_key, session_id, workspace_id, 'ACTIVE', now_iso))
                self.provider_request_key = create_key
                self.provider_fence_token = str(uuid4())
                conn.execute('INSERT INTO codebase_request_fences VALUES(?,?,?)', (create_key, self.provider_fence_token, 'ACTIVE'))
                admitted_create = True
            conn.commit()
            audio_url, audio_bytes = await self._synthesize_audio(session_id, INITIAL_MENTOR_PROMPT, settings)
            if audio_bytes:
                conn.execute("BEGIN IMMEDIATE")
                if self.request is not None:
                    provider_dispatch.owned(conn, self.request, workspace_id, session_id)
                    if self.provider_request_key:
                        provider_dispatch.check_fence(conn, self.provider_request_key, self.provider_fence_token)
                try:
                    audio_url = store_audio(conn, session_id, audio_bytes)
                except ValueError:
                    audio_url = None

            if audio_url:
                conn.execute('UPDATE codebase_learning_messages SET audio_path=? WHERE id=?', (audio_url, msg_id))
            conn.commit()
            return await self.get_session(workspace_id, session_id)
        except BaseException:
            conn.rollback()
            if admitted_create:
                try:
                    provider_dispatch.recover_fenced_request(self.db_path, create_key)
                except ValueError:
                    pass  # Another recovery already fenced it.
            raise
        finally:
            conn.close()
            if admitted_create:
                provider_dispatch.finish(self.db_path, create_key)

    async def list_sessions(self, workspace_id: str, query: str | None = None) -> list[dict[str, Any]]:
        """List active sessions for a workspace grouped by updated_at."""
        conn = open_connection(self.db_path)
        try:
            sql = """SELECT s.*, count(m.id) as message_count
                     FROM codebase_learning_sessions s
                     LEFT JOIN codebase_learning_messages m ON m.session_id=s.id
                     WHERE s.workspace_id=? AND s.deleted_at IS NULL"""
            params: list[Any] = [workspace_id]
            if query and query.strip():
                sql += " AND (s.title LIKE ? OR s.repo_name LIKE ?)"
                like = f"%{query.strip()}%"
                params.extend([like, like])
            sql += " GROUP BY s.id ORDER BY s.updated_at DESC"
            rows = conn.execute(sql, params).fetchall()
            return [
                {
                    "session_id": r["id"],
                    "workspace_id": r["workspace_id"],
                    "repo_snapshot_id": r["repo_snapshot_id"],
                    "repo_url": r["repo_url"],
                    "repo_name": r["repo_name"],
                    "branch": r["branch"],
                    "title": r["title"],
                    "current_topic": r["current_topic"],
                    "knowledge_level": r["knowledge_level"],
                    "message_count": r["message_count"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                }
                for r in rows
            ]
        finally:
            conn.close()

    async def get_session(self, workspace_id: str, session_id: str) -> dict[str, Any]:
        """Fetch session and its full message history."""
        conn = open_connection(self.db_path)
        try:
            s = conn.execute(
                "SELECT * FROM codebase_learning_sessions WHERE id=? AND workspace_id=? AND deleted_at IS NULL",
                (session_id, workspace_id),
            ).fetchone()
            if not s:
                raise LookupError("Session not found.")

            # Load snapshot metadata
            snap = conn.execute("SELECT * FROM repo_snapshots WHERE id=?", (s["repo_snapshot_id"],)).fetchone()
            coverage = json.loads(snap["coverage_json"]) if snap and snap["coverage_json"] else {}

            messages = conn.execute(
                """SELECT id, sequence, role, content, audio_path, citations_json, metadata_json, created_at
                   FROM codebase_learning_messages
                   WHERE session_id=? ORDER BY sequence ASC""",
                (session_id,),
            ).fetchall()

            return {
                "session_id": s["id"],
                "workspace_id": s["workspace_id"],
                "repo_snapshot_id": s["repo_snapshot_id"],
                "repo_url": s["repo_url"],
                "repo_name": s["repo_name"],
                "branch": s["branch"],
                "commit_sha": s["commit_sha"],
                "title": s["title"],
                "current_topic": s["current_topic"],
                "knowledge_level": s["knowledge_level"],
                "learning_progress": json.loads(s["learning_progress_json"] or "{}"),
                "pending_question": s["pending_question"],
                "state": s["state"],
                "created_at": s["created_at"],
                "updated_at": s["updated_at"],
                "snapshot": {
                    "snapshot_id": snap["id"] if snap else s["repo_snapshot_id"],
                    "status": snap["status"] if snap else "READY",
                    "total_files": snap["total_files"] if snap else 0,
                    "files_indexed": snap["files_indexed"] if snap else 0,
                    "architecture": coverage.get("architecture", {}),
                },
                "messages": [
                    {
                        "id": m["id"],
                        "sequence": m["sequence"],
                        "role": m["role"],
                        "content": m["content"],
                        "audio_url": m["audio_path"],
                        "citations": json.loads(m["citations_json"] or "[]"),
                        "metadata": json.loads(m["metadata_json"] or "{}"),
                        "created_at": m["created_at"],
                    }
                    for m in messages
                ],
            }
        finally:
            conn.close()

    async def rename_session(self, workspace_id: str, session_id: str, title: str) -> dict[str, Any]:
        """Update session title."""
        conn = open_connection(self.db_path)
        try:
            clean = title.strip()[:160]
            if not clean:
                raise ValueError("Title cannot be empty.")
            count = conn.execute(
                "UPDATE codebase_learning_sessions SET title=?, updated_at=? WHERE id=? AND workspace_id=? AND deleted_at IS NULL",
                (clean, _now(), session_id, workspace_id),
            ).rowcount
            if not count:
                raise LookupError("Session not found.")
            return await self.get_session(workspace_id, session_id)
        finally:
            conn.close()

    async def delete_session(self, workspace_id: str, session_id: str) -> bool:
        """Soft-delete session."""
        conn = open_connection(self.db_path)
        try:
            count = conn.execute(
                "UPDATE codebase_learning_sessions SET deleted_at=? WHERE id=? AND workspace_id=? AND deleted_at IS NULL",
                (_now(), session_id, workspace_id),
            ).rowcount
            return bool(count)
        finally:
            conn.close()

    def _retrieve_grounding_citations(self, conn: sqlite3.Connection, snapshot_id: str, query: str) -> list[dict[str, Any]]:
        """Retrieve relevant code snippets from FTS index for the snapshot."""
        words = re.findall(r"[A-Za-z0-9_]{3,}", query)
        citations: list[dict[str, Any]] = []
        if not words:
            return citations

        match_terms = " OR ".join(words[:6])
        try:
            rows = conn.execute(
                """SELECT c.path, c.symbol, c.start_line, c.end_line, c.chunk_hash, c.text
                   FROM repo_chunks_fts f
                   JOIN repo_chunks c ON c.id=f.chunk_id
                   WHERE c.snapshot_id=? AND repo_chunks_fts MATCH ?
                   ORDER BY rank LIMIT 3""",
                (snapshot_id, match_terms),
            ).fetchall()
            for r in rows:
                citations.append({
                    "path": r["path"],
                    "symbol": r["symbol"],
                    "start_line": r["start_line"],
                    "end_line": r["end_line"],
                    "chunk_hash": r["chunk_hash"],
                    "excerpt": r["text"][:300].strip(),
                })
        except Exception:
            # Fallback to simple LIKE search on path or symbol
            for w in words[:3]:
                like = f"%{w}%"
                rows = conn.execute(
                    """SELECT path, symbol, start_line, end_line, chunk_hash, text
                       FROM repo_chunks
                       WHERE snapshot_id=? AND (path LIKE ? OR symbol LIKE ?)
                       LIMIT 2""",
                    (snapshot_id, like, like),
                ).fetchall()
                for r in rows:
                    citations.append({
                        "path": r["path"],
                        "symbol": r["symbol"],
                        "start_line": r["start_line"],
                        "end_line": r["end_line"],
                        "chunk_hash": r["chunk_hash"],
                        "excerpt": r["text"][:300].strip(),
                    })
        return citations[:3]

    async def _call_llm_mentor(
        self,
        session_id: str,
        repo_name: str,
        arch_overview: str,
        citations: list[dict[str, Any]],
        conversation_history: list[dict[str, Any]],
        learner_input: str,
        knowledge_level: str,
        settings: Settings,
    ) -> str:
        """Call Groq or generate a grounded Socratic mentor response."""
        key = validated_credential(settings.groq_api_key)
        model = settings.llm_model or "qwen/qwen3.8-27b"

        citation_evidence = "\n".join(
            f"- File: `{c['path']}` ({c['start_line']}-{c['end_line']}):\n{c['excerpt']}"
            for c in citations
        ) if citations else "No specific file queried."

        system_msg = (
            "You are Nexus, a knowledgeable, patient, and interactive AI software architecture mentor. "
            "You are having a spoken voice conversation with a learner exploring a GitHub repository.\n\n"
            "Pedagogical Rules:\n"
            "1. Speak naturally, warmly, and concisely (2 to 4 sentences). The response will be synthesized into voice, "
            "so avoid code blocks, bulleted lists, and complex markdown.\n"
            "2. Adapt strictly to the learner's demonstrated knowledge level.\n"
            "   - If they are a beginner: explain core concepts, build prerequisites, use analogies.\n"
            "   - If they are intermediate: trace how components connect, explain design tradeoffs.\n"
            "   - If they are advanced: analyze failure handling, scalability, and implementation decisions.\n"
            "3. Ground your explanation in real files and functions from the repository evidence provided below. "
            "Refer to actual files like `backend/app/main.py`. Never invent file names or fake line numbers.\n"
            "4. Distinguish observed code from inferred architectural intent.\n"
            "5. Always end with a thoughtful, conversational follow-up question to guide their learning journey."
        )

        user_content = (
            f"Repository: {repo_name}\n"
            f"Architecture: {arch_overview}\n"
            f"Learner Knowledge Level: {knowledge_level}\n\n"
            f"Available Code Evidence:\n{citation_evidence}\n\n"
            f"Learner statement: \"{learner_input}\"\n\n"
            "Provide your conversational mentor response:"
        )

        messages = [{"role": "system", "content": system_msg}]
        # Add recent conversation turns
        for m in conversation_history[-4:]:
            role = "assistant" if m["role"] == "mentor" else "user"
            messages.append({"role": role, "content": m["content"]})
        messages.append({"role": "user", "content": user_content})

        if key:
            try:
                async def dispatch():
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.post(
                            "https://api.groq.com/openai/v1/chat/completions",
                            headers={"Authorization": f"Bearer {key}"},
                            json={
                                "model": model,
                                "messages": messages,
                                "max_tokens": 300,
                                "temperature": 0.3,
                            },
                        )
                    return resp
                resp = await self._dispatch(session_id, 'MODEL', dispatch, settings)
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"].strip()
                    if content:
                        return content
            except HTTPException:
                raise
            except (TimeoutError, httpx.TransportError):
                pass

        # Grounded deterministic fallback if external provider is offline
        if citations:
            c = citations[0]
            return (
                f"Looking at `{c['path']}`, we can see how this component handles its core responsibilities. "
                f"Notice how the symbols are organized between lines {c['start_line']} and {c['end_line']}. "
                "How does this approach compare to what you've seen in other projects?"
            )
        return (
            f"That makes sense. In {repo_name}, the system separates responsibilities cleanly across its modules. "
            "Which part of the architecture would you like to examine next: the API entry points, or the data models?"
        )

    def _infer_knowledge_level(self, text: str, current: str) -> str:
        t = text.lower()
        if any(w in t for w in ("never used", "beginner", "new to", "don't know", "dont know", "learning python", "learning code")):
            return "beginner"
        if any(w in t for w in ("experienced", "senior", "advanced", "architect", "production", "scale", "microservices")):
            return "advanced"
        if any(w in t for w in ("familiar", "know python", "know fastapi", "intermediate", "built some", "used it before")):
            return "intermediate"
        return current if current != "undetermined" else "intermediate"

    async def process_turn(self, workspace_id, session_id, **kwargs):
        self.workspace_id = workspace_id
        key = None
        if self.request is not None:
            key = provider_dispatch.begin(self.db_path, self.request, workspace_id, session_id)
            self.provider_request_key = key
            self.provider_fence_token = provider_dispatch.fence_token(self.db_path, key)
        try:
            return await self._process_turn_inner(workspace_id, session_id, **kwargs)
        except BaseException:
            if key:
                try:
                    provider_dispatch.recover_fenced_request(self.db_path, key)
                except ValueError:
                    pass
            raise
        finally:
            if key:
                provider_dispatch.finish(self.db_path, key)

    async def _process_turn_inner(
        self,
        workspace_id: str,
        session_id: str,
        learner_text: str | None = None,
        audio_wav_bytes: bytes | None = None,
        speech_locale: str = "en-IN",
        settings: Settings | None = None,
    ) -> dict[str, Any]:
        """Process a learner turn (voice or text), reason, synthesize TTS, and persist."""
        cfg = settings or get_settings()
        self.workspace_id = workspace_id
        recognized_transcript: str | None = None

        # Reject missing or foreign sessions before contacting a paid provider.
        with closing(open_connection(self.db_path)) as validation_db:
            owned = validation_db.execute(
                "SELECT 1 FROM codebase_learning_sessions WHERE id=? AND workspace_id=? AND deleted_at IS NULL",
                (session_id, workspace_id),
            ).fetchone()
        if not owned:
            raise LookupError("Session not found.")

        # 1. Handle Voice Input if present
        if audio_wav_bytes:
            if not validated_credential(cfg.gnani_api_key):
                raise ValueError("Voice processing is unavailable because Gnani credentials are not configured.")
            normalized_bytes = _normalize_wav_to_16k_mono(audio_wav_bytes)
            adapter = self._get_adapter(cfg)
            stt_req = STTRequest(session_id=session_id, language_mode=LanguageMode.EN_IN)
            with wave.open(io.BytesIO(normalized_bytes), 'rb') as wav:
                seconds = wav.getnframes() / wav.getframerate()
            if seconds > 30:
                raise ValueError('Voice input exceeds 30 seconds')
            stt_res = await self._dispatch(session_id, 'STT', lambda: adapter.transcribe_rest(stt_req, normalized_bytes), cfg, seconds=seconds)
            recognized_transcript = stt_res.normalized_transcript or stt_res.raw_transcript
            learner_text = recognized_transcript

        if not learner_text or not learner_text.strip():
            raise ValueError("No speech or text provided in turn.")

        learner_text = learner_text.strip()[:4000]

        conn = open_connection(self.db_path)
        try:
            s = conn.execute(
                "SELECT * FROM codebase_learning_sessions WHERE id=? AND workspace_id=? AND deleted_at IS NULL",
                (session_id, workspace_id),
            ).fetchone()
            if not s:
                raise LookupError("Session not found.")

            snapshot_id = s["repo_snapshot_id"]
            repo_name = s["repo_name"]
            current_level = s["knowledge_level"]
            new_level = self._infer_knowledge_level(learner_text, current_level)

            # Load snapshot architecture
            snap = conn.execute("SELECT * FROM repo_snapshots WHERE id=?", (snapshot_id,)).fetchone()
            coverage = json.loads(snap["coverage_json"]) if snap and snap["coverage_json"] else {}
            arch = coverage.get("architecture", {})
            arch_overview = arch.get("overview", f"A software repository containing {snap['files_indexed'] if snap else 0} files.")

            # Retrieve citations
            citations = self._retrieve_grounding_citations(conn, snapshot_id, learner_text)

            # Load past messages
            past_msgs = conn.execute(
                "SELECT role, content FROM codebase_learning_messages WHERE session_id=? ORDER BY sequence ASC",
                (session_id,),
            ).fetchall()
            history = [{"role": m["role"], "content": m["content"]} for m in past_msgs]

            # Reason with LLM mentor
            mentor_reply = await self._call_llm_mentor(
                session_id, repo_name, arch_overview, citations, history, learner_text, new_level, cfg,
            )

            # Synthesize mentor speech
            audio_url, audio_bytes = await self._synthesize_audio(session_id, mentor_reply, cfg)
            conn.execute('BEGIN IMMEDIATE')
            if self.request is not None:
                provider_dispatch.owned(conn, self.request, workspace_id, session_id)
                provider_dispatch.check_fence(conn, self.provider_request_key, self.provider_fence_token)
            if audio_bytes:
                try:
                    audio_url = store_audio(conn, session_id, audio_bytes)
                except ValueError:
                    audio_url = None

            now_iso = _now()
            max_seq = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM codebase_learning_messages WHERE session_id=?",
                (session_id,),
            ).fetchone()[0]

            # Save learner message
            learner_msg_id = _id("clm_")
            conn.execute(
                """INSERT INTO codebase_learning_messages(
                    id, session_id, sequence, role, content, audio_path, citations_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    learner_msg_id, session_id, max_seq + 1, "learner", learner_text, None,
                    "[]", json.dumps({"recognized": bool(audio_wav_bytes)}), now_iso,
                ),
            )

            # Save mentor message
            mentor_msg_id = _id("clm_")
            conn.execute(
                """INSERT INTO codebase_learning_messages(
                    id, session_id, sequence, role, content, audio_path, citations_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    mentor_msg_id, session_id, max_seq + 2, "mentor", mentor_reply, audio_url,
                    json.dumps(citations), json.dumps({"citations_count": len(citations)}), now_iso,
                ),
            )

            # Auto-update session title if default
            updated_title = s["title"]
            if s["title"].startswith("Exploring ") and max_seq >= 2:
                # Infer a concise title from the topic
                words = re.findall(r"[A-Za-z0-9_-]+", learner_text)
                if words:
                    updated_title = f"{repo_name}: {' '.join(words[:4]).title()}"

            conn.execute(
                """UPDATE codebase_learning_sessions
                   SET updated_at=?, knowledge_level=?, title=?, pending_question=?
                   WHERE id=?""",
                (now_iso, new_level, updated_title, mentor_reply, session_id),
            )

            conn.commit()
            return {
                "session_id": session_id,
                "learner_message": {
                    "id": learner_msg_id,
                    "sequence": max_seq + 1,
                    "role": "learner",
                    "content": learner_text,
                    "recognized": bool(audio_wav_bytes),
                    "created_at": now_iso,
                },
                "mentor_message": {
                    "id": mentor_msg_id,
                    "sequence": max_seq + 2,
                    "role": "mentor",
                    "content": mentor_reply,
                    "audio_url": audio_url,
                    "citations": citations,
                    "created_at": now_iso,
                },
                "current_topic": s["current_topic"],
                "knowledge_level": new_level,
            }
        finally:
            conn.close()
