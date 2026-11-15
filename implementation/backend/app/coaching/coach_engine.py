"""Grounded Socratic Coaching Engine with Selectable Model Adapter & Deterministic Fallback (`backend/app/coaching/coach_engine.py`).

Implements Plan §10 / P5 & P6:
- Supports both 100% deterministic coaching (`DeterministicCoachProvider`) and optional bounded
  Groq model-assisted phrasing under a configured bounded deadline and shared durable budget.
- Model assistance can select only approved phrasing. Timeout, HTTP error,
  missing configuration and invalid selection return explicit availability states with an authored fallback.
- Converts the selected display text into Indian English speakable chunks via `to_speakable` (`pre_tts_normalizer.py`).
"""

from __future__ import annotations

from typing import Any
import json

import httpx

try:
    from backend.app.coaching.prompt_guard import (
        validate_model_coaching_output,
        wrap_untrusted_learner_inputs,
    )
    from backend.app.coaching.templates import (
        CoachingHintPrompt,
        render_deterministic_hint,
    )
    from backend.app.models.domain import EvidenceArtifact, TraceExecutionReport
    from backend.app.models.enums import HintLevel, LearningState, RevealState
    from backend.app.speech.pre_tts_normalizer import to_speakable
except ImportError:  # pragma: no cover
    from app.coaching.prompt_guard import (  # type: ignore[no-redef]
        validate_model_coaching_output,
        wrap_untrusted_learner_inputs,
    )
    from app.coaching.templates import (  # type: ignore[no-redef]
        CoachingHintPrompt,
        render_deterministic_hint,
    )
    from app.models.domain import EvidenceArtifact, TraceExecutionReport  # type: ignore[no-redef]
    from app.models.enums import HintLevel, LearningState, RevealState  # type: ignore[no-redef]
    from app.speech.pre_tts_normalizer import to_speakable  # type: ignore[no-redef]


class CoachEngine:
    """Grounded Socratic coach with selectable model-assisted phrasing and deterministic fallback."""

    def __init__(
        self,
        *,
        llm_api_key: str | None = None,
        llm_model: str | None = None,
        llm_endpoint: str = "https://api.groq.com/openai/v1/chat/completions",
        llm_timeout_ms: int = 1200,
        http_client: httpx.Client | None = None,
        settings=None,
    ) -> None:
        from backend.app.core.config import validated_credential
        self._api_key = validated_credential(llm_api_key) or ''
        self._model = llm_model or ''
        if settings is not None:
            self._api_key = (validated_credential(settings.groq_api_key) or '') if settings.llm_provider == 'groq' else ''
            self._model = settings.llm_model if self._api_key else ''
        self._endpoint = llm_endpoint
        self._timeout_sec = min(30, max(0.1, llm_timeout_ms / 1000.0))
        self._http_client = http_client
        self.settings = settings

    def build_coaching_turn_response(
        self,
        *,
        artifact: EvidenceArtifact,
        trace_report: TraceExecutionReport | None,
        learning_state: LearningState,
        hint_level: int | HintLevel = HintLevel.DIAGNOSTIC_QUESTION,
        source_code: str = "",
        learner_utterance: str = "",
    ) -> dict[str, Any]:
        if not isinstance(artifact, EvidenceArtifact):
            raise ValueError("Coaching requires revealed, authorized evidence.")
        if trace_report is not None and (
            trace_report.revision != artifact.revision
            or trace_report.case_hash != artifact.case_hash
        ):
            trace_report = None
        level_enum = HintLevel(int(hint_level))
        det_prompt = render_deterministic_hint(
            artifact,
            hint_level=level_enum,
            trace_report=trace_report,
            learning_state=learning_state,
        )

        final_prompt = det_prompt
        model_status='MODEL_DISABLED' if self.settings and self.settings.llm_provider != 'groq' else 'MODEL_NOT_CONFIGURED'
        max_line = max(1, len(source_code.splitlines())) if source_code else 50

        if (
            self._api_key
            and self._model
            and not self._api_key.startswith("REPLACE_")
            and not self._model.startswith("REPLACE_")
        ):
            model_text, model_status = self._try_model_assisted_rephrase(
                det_prompt=det_prompt,
                artifact=artifact,
                source_code=source_code,
                learner_utterance=learner_utterance,
                max_source_line=max_line,
            )
            if model_text is not None:
                final_prompt = CoachingHintPrompt(
                    hint_level=level_enum,
                    display_text=model_text,
                    pointed_event_id=det_prompt.pointed_event_id,
                    pointed_line=det_prompt.pointed_line,
                    source_mode="MODEL_ASSISTED_APPROVED_PHRASING",
                )

        speakable_chunks = to_speakable(final_prompt.display_text)
        return {
            "hint_level": int(final_prompt.hint_level),
            "display_text": final_prompt.display_text,
            "speakable_chunks": speakable_chunks,
            "speakable_text": " ".join(speakable_chunks),
            "pointed_event_id": final_prompt.pointed_event_id,
            "pointed_line": final_prompt.pointed_line,
            "source_mode": final_prompt.source_mode,
            "model_status": model_status,
        }

    def _try_model_assisted_rephrase(
        self,
        *,
        det_prompt: CoachingHintPrompt,
        artifact: EvidenceArtifact,
        source_code: str,
        learner_utterance: str,
        max_source_line: int,
    ) -> tuple[str | None, str]:
        from backend.app.coaching import model_budget
        from backend.app.coaching.model_http import post_model, ModelThreadRequired
        from backend.app.db.repository import RevisionConflictError
        session_id = str(artifact.revision.session_id)
        if self.settings is None and self._http_client is None:
            return None, 'MODEL_NOT_CONFIGURED'
        reservation = model_budget.reserve(self.settings,session_id,'coaching_phrase',artifact.revision) if self.settings else None
        if self.settings is not None and not reservation:
            return None, 'MODEL_RATE_LIMITED'
        # Model assistance selects an approved phrasing rather than inventing
        # new factual assertions. Every candidate keeps the same verified fact.
        choices = [
            det_prompt.display_text,
            "Let's work through this together. " + det_prompt.display_text,
        ]
        wrapped_untrusted = wrap_untrusted_learner_inputs(
            source_code, learner_utterance
        )
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": "Choose the clearest approved coaching phrasing for this learner. Return only JSON with integer choice 0 or 1. Do not write or alter any coaching facts.",
                },
                {
                    "role": "user",
                    "content": json.dumps({"approved_choices": choices})
                    + "\n"
                    + wrapped_untrusted,
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": 20,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        accounting='UNDISPATCHED'
        try:
            if self.settings: model_budget.assert_current(self.settings,session_id,artifact.revision)
            accounting='UNCERTAIN'
            resp=post_model(self._endpoint,payload=payload,headers=headers,timeout_seconds=self._timeout_sec,client=self._http_client)
            accounting='COMMITTED'
            if self.settings: model_budget.assert_current(self.settings,session_id,artifact.revision)
            if resp.status_code != 200:
                return None, 'MODEL_RATE_LIMITED' if resp.status_code == 429 else 'MODEL_UNAVAILABLE'
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str) or len(content) > 128:
                return None, 'MODEL_INVALID_RESPONSE'
            selection = json.loads(content)
            if not isinstance(selection, dict):
                return None, 'MODEL_INVALID_RESPONSE'
            choice = selection.get("choice")
            if (
                type(choice) is not int
                or choice not in (0, 1)
                or set(selection) != {"choice"}
            ):
                return None, 'MODEL_INVALID_RESPONSE'
            return choices[choice], 'MODEL_ASSISTED'
        except RevisionConflictError: raise
        except ModelThreadRequired:
            accounting='UNDISPATCHED'
            return None, 'MODEL_UNAVAILABLE'
        except (httpx.TimeoutException, TimeoutError): return None, 'MODEL_TIMEOUT'
        except httpx.HTTPError: return None, 'MODEL_UNAVAILABLE'
        except (ValueError, TypeError, KeyError, IndexError): return None, 'MODEL_INVALID_RESPONSE'
        finally:
            if reservation: model_budget.settle(self.settings,reservation,accounting)
