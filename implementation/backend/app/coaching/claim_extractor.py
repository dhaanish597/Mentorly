"""Deterministic & Model-Assisted Learner Claim Extractor (`backend/app/coaching/claim_extractor.py`).

Implements Plan §6.1 / §8.3 / P3 & P5:
- Parses learner transcripts or typed turns into a structured `ClaimInterpretation` discriminated union:
  - `OutputPredictionClaim` (`OUTPUT_PREDICTION_AND_REASON`)
  - `InvariantOrMechanismClaim` (`INVARIANT_OR_MECHANISM_CLAIM`)
  - `DomainValidityClaim` (`DOMAIN_VALIDITY_CLAIM`)
  - `ClarificationOrHintClaim` (`CLARIFICATION_OR_HINT_REQUEST`)
  - `UnsupportedClaim` (`UNSUPPORTED_CLAIM`)
- Never sets `confirmed_at` automatically during extraction (`confirmed_at=None`), preserving the mandatory
  learner confirmation gate before reveal or coaching.
"""

from __future__ import annotations

import re
from uuid import UUID

try:
    from backend.app.models.domain import (
        ClaimInterpretation,
        ClarificationOrHintClaim,
        DomainValidityClaim,
        InvariantOrMechanismClaim,
        OutputPredictionClaim,
        UnsupportedClaim,
    )
    from backend.app.models.enums import (
        ClaimPolarity,
        ExtractionMethod,
        SpecVersion,
    )
    from backend.app.speech.transcript_normalizer import normalize_learner_transcript
except ImportError:  # pragma: no cover
    from app.models.domain import (  # type: ignore[no-redef]
        ClaimInterpretation,
        ClarificationOrHintClaim,
        DomainValidityClaim,
        InvariantOrMechanismClaim,
        OutputPredictionClaim,
        UnsupportedClaim,
    )
    from app.models.enums import (  # type: ignore[no-redef]
        ClaimPolarity,
        ExtractionMethod,
        SpecVersion,
    )
    from app.speech.transcript_normalizer import normalize_learner_transcript  # type: ignore[no-redef]

_HINT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:hint|help|not\s+sure|why\s+does|what\s+happens|explain|clue)\b",
        re.IGNORECASE,
    ),
)

_DOMAIN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:negative(?:s)?|sliding\s+window\s+breaks|monotonic(?:ity)?|v2_negatives_allowed)\b",
        re.IGNORECASE,
    ),
)

_INVARIANT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:loop|invariant|window|sliding_window|binary_search|max_product|pointer|left|right|mid|curr_sum|max_prod|min_prod|prefix_sum|sorted|boundary)\b",
        re.IGNORECASE,
    ),
)


def extract_claim_deterministic(
    raw_or_normalized_text: str,
    *,
    challenge_id: UUID | None = None,
    target_spec_version: SpecVersion = SpecVersion.EX1_V2_NEGATIVES_ALLOWED,
    provider_confidence: float | None = None,
    known_identifiers: list[str] | None = None,
) -> ClaimInterpretation:
    """Deterministically extract a unconfirmed `ClaimInterpretation` proposal from learner speech/text."""
    norm_prop = normalize_learner_transcript(
        raw_or_normalized_text, known_identifiers=known_identifiers
    )
    text = norm_prop.normalized_transcript.strip()
    if not text:
        return UnsupportedClaim(
            challenge_id=challenge_id,
            critical_tokens=[],
            provider_confidence=provider_confidence,
            extraction_method=ExtractionMethod.DETERMINISTIC,
            confirmed_at=None,
            raw_summary="Empty transcript",
        )

    # Typed JSON predictions are proposals only; never evaluate imported text.
    if challenge_id is not None:
        import json
        from backend.app.exercises.values import validate_value
        marker = re.search(r'\b(?:returns?|outputs?|gives?|result\s+is|answer\s+is|predict(?:ion)?\s+is|it\s+is|value\s+is)\s+', text, re.IGNORECASE)
        candidate = text[marker.end():] if marker else raw_or_normalized_text.strip()
        candidate = re.sub(r'^(true|false)\b', lambda m: m.group(0).lower(), candidate, flags=re.IGNORECASE)
        try:
            val, end = json.JSONDecoder().raw_decode(candidate)
            if candidate[end:].strip() and not re.match(r'^\s*because\b', candidate[end:], re.IGNORECASE):
                raise ValueError('Ambiguous prediction suffix')
            validate_value(val)
        except (ValueError, TypeError, RecursionError):
            val = None
        if val is not None:
            tokens = [json.dumps(val, ensure_ascii=False)]
            tokens += [ident for ident in known_identifiers or [] if ident in text][:15]
            return OutputPredictionClaim(
                challenge_id=challenge_id, predicted_output=val, reason_summary=text[:1024],
                polarity=ClaimPolarity.AFFIRMATIVE, critical_tokens=tokens,
                provider_confidence=provider_confidence,
                extraction_method=ExtractionMethod.DETERMINISTIC, confirmed_at=None,
            )

    # 2. Hint or clarification request
    if any(p.search(text) for p in _HINT_PATTERNS) or text.endswith("?"):
        return ClarificationOrHintClaim(
            challenge_id=challenge_id,
            question_text=text[:1024],
            critical_tokens=[],
            provider_confidence=provider_confidence,
            extraction_method=ExtractionMethod.DETERMINISTIC,
            confirmed_at=None,
        )

    # 3. Domain validity claim (e.g., negative numbers breaking monotone sliding window)
    if any(p.search(text) for p in _DOMAIN_PATTERNS):
        polarity = (
            ClaimPolarity.NEGATIVE
            if re.search(
                r"\b(?:breaks?|fails?|invalid|not|cannot|doesn't)\b",
                text,
                re.IGNORECASE,
            )
            else ClaimPolarity.AFFIRMATIVE
        )
        return DomainValidityClaim(
            challenge_id=challenge_id,
            target_spec_version=target_spec_version,
            polarity=polarity,
            critical_tokens=["v2_negatives_allowed"],
            provider_confidence=provider_confidence,
            extraction_method=ExtractionMethod.DETERMINISTIC,
            confirmed_at=None,
        )

    # 4. Invariant or mechanism explanation
    if any(p.search(text) for p in _INVARIANT_PATTERNS):
        return InvariantOrMechanismClaim(
            challenge_id=challenge_id,
            mechanism_summary=text[:1024],
            polarity=ClaimPolarity.AFFIRMATIVE,
            critical_tokens=[],
            provider_confidence=provider_confidence,
            extraction_method=ExtractionMethod.DETERMINISTIC,
            confirmed_at=None,
        )

    return UnsupportedClaim(
        challenge_id=challenge_id,
        raw_summary=text[:1024],
        critical_tokens=[],
        provider_confidence=provider_confidence,
        extraction_method=ExtractionMethod.DETERMINISTIC,
        confirmed_at=None,
    )


class ModelAssistedClaimExtractor:
    """Schema-validated optional extraction; proposals always require human confirmation.

    No reference answer, execution result, or hidden evidence enters the model.
    Invalid/uncertain/provider-failed proposals fall back to deterministic extraction.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        endpoint: str = "https://api.groq.com/openai/v1/chat/completions",
        http_client=None,
        settings=None,
    ):
        from backend.app.core.config import validated_credential
        self.api_key = validated_credential(api_key) or ''
        self.model = model or ''
        if settings is not None:
            self.api_key = (validated_credential(settings.groq_api_key) or '') if settings.llm_provider == 'groq' else ''
            self.model = settings.llm_model if self.api_key else ''
        self.endpoint = endpoint
        self.http_client = http_client
        self.settings = settings
        self.timeout_seconds = min(30,max(.1,settings.llm_timeout_ms / 1000)) if settings else 1.2

    def extract(
        self,
        text: str,
        *,
        challenge_id: UUID | None = None,
        target_spec_version: SpecVersion = SpecVersion.EX1_V2_NEGATIVES_ALLOWED,
        provider_confidence: float | None = None,
        known_identifiers: list[str] | None = None,
        session_id: str | None = None,
        revision=None,
    ) -> ClaimInterpretation:
        import json
        import httpx
        from pydantic import TypeAdapter
        from backend.app.coaching.prompt_guard import wrap_untrusted_learner_inputs
        from backend.app.coaching import model_budget
        from backend.app.coaching.model_http import post_model, ModelThreadRequired
        from backend.app.db.repository import RevisionConflictError

        fallback = extract_claim_deterministic(
            text,
            challenge_id=challenge_id,
            target_spec_version=target_spec_version,
            provider_confidence=provider_confidence,
            known_identifiers=known_identifiers,
        )
        if not self.api_key or not self.model:
            return fallback.model_copy(update={'model_status':'MODEL_DISABLED' if self.settings and self.settings.llm_provider != 'groq' else 'MODEL_NOT_CONFIGURED'})
        if self.settings is not None and session_id is None:
            return fallback.model_copy(update={'model_status':'MODEL_NOT_CONFIGURED'})
        if self.settings is None and self.http_client is None:
            return fallback.model_copy(update={'model_status':'MODEL_NOT_CONFIGURED'})
        reservation = model_budget.reserve(self.settings,session_id,'claim_extraction',revision) if self.settings else None
        if self.settings is not None and not reservation:
            return fallback.model_copy(update={'model_status':'MODEL_RATE_LIMITED'})
        schema = TypeAdapter(ClaimInterpretation)
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 400,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": "Extract only what the learner explicitly says as one JSON claim. Never solve the exercise. "
                    "Use UNSUPPORTED_CLAIM when unsure. Never confirm. Return exactly the discriminated claim schema: "
                    + json.dumps(schema.json_schema()),
                },
                {
                    "role": "user",
                    "content": f"Challenge ID: {challenge_id}\n"
                    + wrap_untrusted_learner_inputs("", text),
                },
            ],
        }
        accounting='UNDISPATCHED'
        status='MODEL_INVALID_RESPONSE'
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            if self.settings: model_budget.assert_current(self.settings,session_id,revision)
            accounting='UNCERTAIN'
            response=post_model(self.endpoint,payload=payload,headers=headers,timeout_seconds=self.timeout_seconds,client=self.http_client)
            accounting='COMMITTED'
            if self.settings: model_budget.assert_current(self.settings,session_id,revision)
            if response.status_code != 200:
                status='MODEL_RATE_LIMITED' if response.status_code == 429 else 'MODEL_UNAVAILABLE'
                return fallback.model_copy(update={'model_status':status})
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or len(content) > 8000:
                return fallback.model_copy(update={'model_status':status})
            claim = schema.validate_json(content)
            if claim.confirmed_at is not None or claim.challenge_id != challenge_id:
                return fallback.model_copy(update={'model_status':status})
            return claim.model_copy(
                update={
                    "extraction_method": ExtractionMethod.MODEL_ASSISTED,
                    "provider_confidence": provider_confidence,
                    "confirmed_at": None,
                    "model_status": 'MODEL_ASSISTED',
                }
            )
        except RevisionConflictError: raise
        except ModelThreadRequired:
            accounting='UNDISPATCHED'; status='MODEL_UNAVAILABLE'
        except (httpx.TimeoutException, TimeoutError): status='MODEL_TIMEOUT'
        except httpx.HTTPError: status='MODEL_UNAVAILABLE'
        except RuntimeError: status='MODEL_UNAVAILABLE'
        except (ValueError, TypeError, KeyError, IndexError): status='MODEL_INVALID_RESPONSE'
        finally:
            if reservation: model_budget.settle(self.settings,reservation,accounting)
        return fallback.model_copy(update={'model_status':status})
