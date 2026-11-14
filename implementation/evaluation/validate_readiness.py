"""Validate local evaluation metadata only; never open audio or execute source."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

DEFAULT_MANIFEST = Path(__file__).parent / "speech_ablation/audio_manifest.json"
LANGUAGES = {"en-IN", "ta-IN,en-IN"}
SPLITS = {"development", "heldout"}
HASH = re.compile(r"[a-f0-9]{64}")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def split_digest(speakers: list[dict[str, Any]]) -> str:
    return digest(sorted(({"speaker_id": s["speaker_id"], "split": s["split"]} for s in speakers), key=lambda s: s["speaker_id"]))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _local_ref(value: Any) -> bool:
    if not _text(value) or ":" in value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and value not in {".", ""}


def _validate_speakers(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    speakers = data.get("speakers")
    _require(isinstance(speakers, list) and len(speakers) == 4, "Exactly four speaker slots required")
    _require(all(isinstance(s, dict) and _text(s.get("speaker_id")) and s.get("split") in SPLITS for s in speakers), "Invalid speaker slot or split")
    by_id = {s["speaker_id"]: s for s in speakers}
    _require(len(by_id) == 4, "Duplicate speaker slots")
    _require(all(sum(s["split"] == split for s in speakers) == 2 for split in SPLITS), "Two speakers per split required")
    _require(data.get("split_sha256") == split_digest(speakers), "Frozen split hash mismatch")
    for speaker in speakers:
        consent = speaker.get("consent_status")
        _require(consent in {"PENDING", "GRANTED"}, "Invalid consent status")
        if consent == "GRANTED":
            _require(speaker.get("participant_status") == "ENROLLED" and _local_ref(speaker.get("consent_ref")), "Granted consent requires enrolled human and local consent record")
            try:
                expiry = datetime.fromisoformat(speaker["retention_expires_at"])
                _require(expiry.tzinfo is not None, "Retention expiry needs timezone")
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Consent requires explicit retention expiry") from exc
        else:
            _require(speaker.get("participant_status") == "PENDING_RECRUITMENT" and speaker.get("consent_ref") is None, "Pending slots must not claim participation or consent")
    return by_id


def _validate_clip(clip: dict[str, Any], speaker: dict[str, Any]) -> bool:
    _require(clip.get("language_mode") in LANGUAGES, "Only English and Tanglish are planned")
    _require(clip.get("status") in {"PENDING_HUMAN_RECORDING", "READY"}, "Invalid recording status")
    if clip["status"] == "PENDING_HUMAN_RECORDING":
        _require(all(clip.get(k) is None for k in ("local_audio_ref", "audio_sha256", "reference_text", "reference_tokens")), "Pending clips cannot claim audio or human references")
        _require(clip.get("reference_status") == "PENDING_HUMAN_ANNOTATION", "Pending annotation status required")
        return False
    _require(speaker["consent_status"] == "GRANTED", "Ready clip requires consenting human")
    _require(_local_ref(clip.get("local_audio_ref")), "Audio reference must be relative and local; no upload")
    _require(isinstance(clip.get("audio_sha256"), str) and HASH.fullmatch(clip["audio_sha256"]) is not None, "Audio SHA-256 required")
    _require(_text(clip.get("reference_text")) and clip.get("reference_status") == "HUMAN_REVIEWED", "Human-reviewed transcript required")
    tokens = clip.get("reference_tokens")
    _require(isinstance(tokens, list) and bool(tokens) and all(_text(t) for t in tokens), "Human reference tokens required")
    return True


def validate_manifest(data: Any) -> dict[str, Any]:
    _require(isinstance(data, dict), "Manifest must be an object")
    _require(data.get("schema_version") == "2.0.0", "Unsupported manifest version")
    privacy = data.get("privacy")
    _require(isinstance(privacy, dict) and privacy.get("no_upload") is True and privacy.get("local_only") is True, "Explicit local-only/no-upload policy required")
    speakers = _validate_speakers(data)
    clips = data.get("clips")
    _require(isinstance(clips, list) and len(clips) == 24, "Exactly 24 clips required")
    _require(all(isinstance(c, dict) and _text(c.get("clip_id")) and c.get("speaker_id") in speakers for c in clips), "Invalid clip or unknown speaker")
    _require(len({c["clip_id"] for c in clips}) == 24, "Duplicate clip IDs")
    for speaker_id in speakers:
        for language in LANGUAGES:
            _require(sum(c["speaker_id"] == speaker_id and c.get("language_mode") == language for c in clips) == 3, "Each speaker needs three English and three Tanglish clips")
    ready_count = sum(_validate_clip(c, speakers[c["speaker_id"]]) for c in clips)
    _require(type(data.get("frozen")) is bool, "Explicit freeze status required")
    frozen = data["frozen"]
    if frozen:
        _require(ready_count == 24, "Cannot freeze incomplete human dataset")
        _require(data.get("manifest_sha256") == digest({k: v for k, v in data.items() if k != "manifest_sha256"}), "frozen manifest hash mismatch")
    else:
        _require(data.get("manifest_sha256") is None, "Unfrozen dataset must not claim a manifest hash")
    return {
        "status": "READY_LOCAL" if frozen else "BLOCKED_EXTERNAL",
        "clips_total": 24, "clips_ready": ready_count,
        "speakers_consented": sum(s["consent_status"] == "GRANTED" for s in speakers.values()),
        "split_counts": {split: sum(speakers[c["speaker_id"]]["split"] == split for c in clips) for split in sorted(SPLITS)},
        "frozen": frozen, "audio_bytes_verified": False,
        "limitation": "Metadata only; no recordings, identities, consent authenticity or audio bytes verified. No speech accuracy measured.",
    }


def freeze_manifest(data: dict[str, Any]) -> dict[str, Any]:
    result = validate_manifest(data)
    _require(result["clips_ready"] == 24 and result["speakers_consented"] == 4, "Freeze requires 24 human-annotated clips and four consenting speakers")
    frozen = deepcopy(data) | {"frozen": True}
    frozen = frozen | {"manifest_sha256": digest({k: v for k, v in frozen.items() if k != "manifest_sha256"})}
    validate_manifest(frozen)
    return frozen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, nargs="?", default=DEFAULT_MANIFEST)
    parser.add_argument("--freeze-output", type=Path, help="Write frozen metadata locally; never reads audio")
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
        if args.freeze_output:
            data = freeze_manifest(data)
            with args.freeze_output.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        result = validate_manifest(data)
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "INVALID", "reason": str(exc)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "READY_LOCAL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
