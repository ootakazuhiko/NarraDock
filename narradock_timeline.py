"""Bind private chapter intervals to a selected, freshly measured PCM clock."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any
import unicodedata

from narradock_audio import measure_candidate_wav
from narradock_candidates import (TRANSCRIPT_SCHEMA_VERSION, candidate_fingerprint,
                                 snapshot_candidate)
import narradock_transcript as transcripts

SCHEMA_VERSION = "media-timeline-0.1"
RECEIPT_SCHEMA_VERSION = "media-timeline-verification-0.1"
MAX_BYTES = 256 * 1024
MAX_RESULT_BYTES = 512 * 1024
MAX_CHAPTERS = 1000
MAX_TITLE = 200
MAX_SECONDS = 24 * 60 * 60
IDENTIFIER = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
DIGEST = re.compile(r"[0-9a-f]{64}")
LANGUAGE = re.compile(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*")
ERROR = "Media timeline could not be validated"


class TimelineError(ValueError):
    """A fixed diagnostic without supplied text, file paths or I/O details."""


def _fields(value: Any, fields: set[str]) -> None:
    if (type(value) is not dict or len(value) != len(fields)
            or any(type(key) is not str for key in value) or set(value) != fields):
        raise TimelineError(ERROR)


def _identifier(value: Any) -> bool:
    return type(value) is str and 1 <= len(value) <= 64 and IDENTIFIER.fullmatch(value) is not None


def _digest(value: Any) -> bool:
    return type(value) is str and len(value) == 64 and DIGEST.fullmatch(value) is not None


def _integer(value: Any, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _title(value: Any) -> bool:
    return (type(value) is str and 1 <= len(value) <= MAX_TITLE
            and bool(value.strip()) and value == value.strip()
            and not any(unicodedata.category(char).startswith("C")
                        or char in "\u2028\u2029" for char in value))


def _canonical(document: dict, limit: int) -> bytes:
    result = bytearray()
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False)
    for part in encoder.iterencode(document):
        encoded = part.encode("utf-8")
        if len(result) + len(encoded) > limit:
            raise TimelineError(ERROR)
        result.extend(encoded)
    return bytes(result)


def _snapshot(document: Any, project_id: str) -> dict:
    _fields(document, {"schema_version", "project_id", "content_id", "language",
                       "candidate_fingerprint", "transcript_fingerprint", "clock", "chapters"})
    schema, project, content = document["schema_version"], document["project_id"], document["content_id"]
    language = document["language"]
    candidate_revision, transcript_revision = document["candidate_fingerprint"], document["transcript_fingerprint"]
    if (type(schema) is not str or schema != SCHEMA_VERSION
            or not all(_identifier(value) for value in (project_id, project, content))
            or project != project_id or type(language) is not str or len(language) > 20
            or LANGUAGE.fullmatch(language) is None
            or not _digest(candidate_revision) or not _digest(transcript_revision)):
        raise TimelineError(ERROR)
    clock = document["clock"]
    _fields(clock, {"sample_rate_hz", "frame_count"})
    rate, frames = clock["sample_rate_hz"], clock["frame_count"]
    if not _integer(rate, 8000, 192000) or not _integer(frames, 1, rate * MAX_SECONDS):
        raise TimelineError(ERROR)
    chapters = document["chapters"]
    if type(chapters) is not list or not 1 <= len(chapters) <= MAX_CHAPTERS:
        raise TimelineError(ERROR)
    entries = chapters[:MAX_CHAPTERS + 1]
    if not 1 <= len(entries) <= MAX_CHAPTERS:
        raise TimelineError(ERROR)
    copied, identifiers, previous_end = [], set(), 0
    for chapter in entries:
        _fields(chapter, {"id", "title", "start_frame", "end_frame"})
        identifier, title = chapter["id"], chapter["title"]
        start, end = chapter["start_frame"], chapter["end_frame"]
        if (not _identifier(identifier) or identifier in identifiers or not _title(title)
                or not _integer(start, previous_end, frames)
                or not _integer(end, 1, frames) or start >= end):
            raise TimelineError(ERROR)
        identifiers.add(identifier)
        previous_end = end
        copied.append({"id": identifier, "title": title, "start_frame": start, "end_frame": end})
    snapshot = {"schema_version": schema, "project_id": project, "content_id": content,
                "language": language, "candidate_fingerprint": candidate_revision,
                "transcript_fingerprint": transcript_revision,
                "clock": {"sample_rate_hz": rate, "frame_count": frames}, "chapters": copied}
    _canonical(snapshot, MAX_BYTES)
    return snapshot


def snapshot_timeline(document: Any, *, project_id: str) -> dict:
    """Copy and validate structure only; no bytes, timing or approval are verified."""
    try:
        return _snapshot(document, project_id)
    except (ValueError, TypeError, KeyError, RuntimeError, RecursionError):
        raise TimelineError(ERROR) from None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise TimelineError(ERROR)
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise TimelineError(ERROR)


def load_timeline(data: bytes, *, project_id: str) -> dict:
    """Parse bounded UTF-8 JSON bytes without opening any referenced asset."""
    try:
        if type(data) is not bytes or not 1 <= len(data) <= MAX_BYTES:
            raise TimelineError(ERROR)
        return _snapshot(json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object,
                                    parse_constant=_reject_constant), project_id)
    except (ValueError, TypeError, KeyError, RuntimeError, RecursionError):
        raise TimelineError(ERROR) from None


def timeline_fingerprint(document: Any, *, project_id: str) -> str:
    """Identify the complete canonical sidecar, not its raw file or an approval."""
    try:
        return hashlib.sha256(_canonical(_snapshot(document, project_id), MAX_BYTES)).hexdigest()
    except (ValueError, TypeError, KeyError, RuntimeError, RecursionError):
        raise TimelineError(ERROR) from None


def verify_timeline(document: Any, *, project_id: str, expected_fingerprint: str,
                    candidate: Any, expected_candidate_fingerprint: str,
                    transcript: Any, registry: Any, project_root: Path) -> dict:
    """Verify selected chapter timing against one fresh guarded PCM asset read.

    The caller independently selects the candidate and timeline. No supplied
    measurement receipt is trusted. Nothing is written or automatically remapped;
    verification is not semantic chapter alignment, media QA or approval.
    """
    try:
        timeline = _snapshot(document, project_id)
        revision = hashlib.sha256(_canonical(timeline, MAX_BYTES)).hexdigest()
        selected = snapshot_candidate(candidate, project_id=project_id)
        candidate_revision = candidate_fingerprint(selected, project_id=project_id)
        if (not _digest(expected_fingerprint) or revision != expected_fingerprint
                or not _digest(expected_candidate_fingerprint)
                or candidate_revision != expected_candidate_fingerprint
                or selected["schema_version"] != TRANSCRIPT_SCHEMA_VERSION
                or timeline["candidate_fingerprint"] != candidate_revision
                or timeline["content_id"] != selected["content_id"]
                or timeline["language"] != selected["metadata"]["language"]):
            raise TimelineError(ERROR)
        sidecar = transcripts.snapshot_transcript(transcript)
        audio = selected["audio"]
        transcripts.require_binding(sidecar, {"project_id": selected["project_id"],
            "content_id": selected["content_id"],
            "audio": {key: audio[key] for key in ("asset_id", "sha256", "duration_ms")}})
        transcript_revision = hashlib.sha256(transcripts.canonical_transcript_bytes(sidecar)).hexdigest()
        if (sidecar["language"] != timeline["language"]
                or transcript_revision != selected["transcript"]["fingerprint"]
                or transcript_revision != timeline["transcript_fingerprint"]):
            raise TimelineError(ERROR)
        # All declared selections and sidecar bindings are checked before I/O.
        measurements = measure_candidate_wav(selected, project_id=project_id,
            expected_fingerprint=candidate_revision, registry=registry, project_root=project_root)
        clock = timeline["clock"]
        if (measurements["duration"]["matches_declared"] is not True
                or any(clock[key] != measurements["pcm"][key] for key in clock)):
            raise TimelineError(ERROR)
        rate = clock["sample_rate_hz"]
        # Convert absolute boundaries, never add rounded chapter durations.
        chapters = [{**chapter,
            "start_ms": (2 * chapter["start_frame"] * 1000 + rate) // (2 * rate),
            "end_ms": (2 * chapter["end_frame"] * 1000 + rate) // (2 * rate)}
            for chapter in timeline["chapters"]]
        result = {"schema_version": RECEIPT_SCHEMA_VERSION,
            "scope": "candidate_pcm_chapter_timeline_only", "bytes_verified": True,
            "clock_verified": True, "timeline_fingerprint": revision,
            "candidate_fingerprint": candidate_revision, "transcript_fingerprint": transcript_revision,
            "project_id": timeline["project_id"], "content_id": timeline["content_id"],
            "language": timeline["language"], "clock": clock, "chapters": chapters,
            "rounding": "absolute_frame_nearest_ms_half_up", "measurements": measurements,
            "rights_verified": False, "media_qa_passed": False, "human_reviewed": False,
            "transcript_alignment_verified": False, "chapter_alignment_verified": False,
            "packaged": False, "external_transfer": False, "publication": False}
        _canonical(result, MAX_RESULT_BYTES)
        return result
    except (ValueError, TypeError, KeyError, RuntimeError, RecursionError, OSError):
        raise TimelineError(ERROR) from None
