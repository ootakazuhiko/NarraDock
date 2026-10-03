"""Offline timed-transcript validation and plain-text WebVTT export; no media I/O."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "timed-transcript-0.1"
MAX_BYTES = 2 * 1024 * 1024
MAX_CUES = 10000
MAX_TEXT = 4000
MAX_DURATION_MS = 24 * 60 * 60 * 1000
IDENTIFIER = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")


class TranscriptError(ValueError):
    """Invalid input; diagnostics never include supplied values."""


def _object(value: Any, keys: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise TranscriptError(f"Invalid {label} fields")


def _identifier(value: Any) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= 64
            and IDENTIFIER.fullmatch(value) is not None)


def _milliseconds(value: Any, minimum: int = 0) -> bool:
    return type(value) is int and minimum <= value <= MAX_DURATION_MS


def _audio(value: Any) -> None:
    _object(value, {"asset_id", "sha256", "duration_ms"}, "audio")
    if not _identifier(value["asset_id"]):
        raise TranscriptError("Invalid audio identifier")
    if not isinstance(value["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"]):
        raise TranscriptError("Invalid audio digest")
    if not _milliseconds(value["duration_ms"], 1):
        raise TranscriptError("Invalid audio duration")


def _scope(value: dict[str, Any]) -> None:
    if not all(_identifier(value[key]) for key in ("project_id", "content_id")):
        raise TranscriptError("Invalid scope identifier")
    _audio(value["audio"])


def validate(document: Any) -> None:
    """Validate the restricted contract, not audio bytes, rights, or permission."""
    _object(document, {"schema_version", "project_id", "content_id", "language", "audio", "cues"},
            "transcript")
    if document["schema_version"] != SCHEMA_VERSION:
        raise TranscriptError("Unsupported transcript schema")
    _scope(document)
    language = document["language"]
    if (not isinstance(language, str) or len(language) > 20
            or not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", language)):
        raise TranscriptError("Unsupported language tag shape")
    cues = document["cues"]
    if not isinstance(cues, list) or not 1 <= len(cues) <= MAX_CUES:
        raise TranscriptError("Invalid cue count")
    previous_end = 0
    identifiers: set[str] = set()
    for cue in cues:
        _object(cue, {"id", "start_ms", "end_ms", "text"}, "cue")
        if not _identifier(cue["id"]) or cue["id"] in identifiers:
            raise TranscriptError("Invalid or duplicate cue identifier")
        start, end = cue["start_ms"], cue["end_ms"]
        if (not _milliseconds(start) or not _milliseconds(end, 1)
                or not previous_end <= start < end <= document["audio"]["duration_ms"]):
            raise TranscriptError("Invalid cue timing or overlap")
        text = cue["text"]
        if (not isinstance(text, str) or not 1 <= len(text) <= MAX_TEXT
                or text != text.strip()
                or any(unicodedata.category(char).startswith("C")
                       or char in "\u2028\u2029" for char in text)):
            raise TranscriptError("Invalid single-line cue text")
        identifiers.add(cue["id"])
        previous_end = end


def require_binding(document: Any, expected: Any) -> None:
    """Compare caller-supplied scope/audio references; not an access-control check.

    The caller must obtain expected from an independently trusted candidate
    registry. Copying expected from the transcript proves nothing about media.
    """
    validate(document)
    _object(expected, {"project_id", "content_id", "audio"}, "expected binding")
    _scope(expected)
    if any(document[key] != expected[key] for key in ("project_id", "content_id", "audio")):
        raise TranscriptError("Transcript binding mismatch")


def fingerprint(document: Any) -> str:
    """Identify this complete sidecar revision, without granting approval."""
    validate(document)
    canonical = json.dumps(document, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TranscriptError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise TranscriptError("Non-finite JSON value")


def load_transcript(path: Path) -> dict[str, Any]:
    """Read only the caller's explicit file; never resolve embedded references."""
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise TranscriptError("Transcript exceeds size limit")
        document = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object,
                              parse_constant=_reject_constant)
        validate(document)
        return document
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        if isinstance(error, TranscriptError):
            raise
        raise TranscriptError("Transcript could not be read as valid UTF-8 JSON") from error


def _timestamp(milliseconds: int) -> str:
    seconds, fraction = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{fraction:03d}"


def to_webvtt(document: Any) -> str:
    """Return deterministic WebVTT with escaped plain text and no cue markup."""
    validate(document)
    blocks = ["WEBVTT"]
    for cue in document["cues"]:
        timing = f"{_timestamp(cue['start_ms'])} --> {_timestamp(cue['end_ms'])}"
        blocks.append(f"{cue['id']}\n{timing}\n{html.escape(cue['text'], quote=False)}")
    return "\n\n".join(blocks) + "\n\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "vtt"))
    parser.add_argument("transcript", type=Path)
    args = parser.parse_args(argv)
    try:
        document = load_transcript(args.transcript)
        if args.command == "vtt":
            output = to_webvtt(document)
        else:
            output = json.dumps({"valid": True, "scope": "structure_only",
                                 "cue_count": len(document["cues"]),
                                 "transcript_fingerprint": fingerprint(document),
                                 "media_verified": False, "binding_verified": False,
                                 "external_transfer": False, "publication": False},
                                sort_keys=True, indent=2) + "\n"
        sys.stdout.write(output)
    except (TranscriptError, OSError, UnicodeError) as error:
        message = str(error) if isinstance(error, TranscriptError) else "Output could not be written"
        print(f"Invalid transcript: {message}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    # UTF-8 output also when redirected by Windows shells; no file is created here.
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
