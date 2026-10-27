"""Validate private playback notes against a selected candidate; no media or file I/O."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from narradock_candidates import (CandidateError, TRANSCRIPT_SCHEMA_VERSION,
                                 candidate_fingerprint, snapshot_candidate)
import narradock_transcript as transcripts

SCHEMA_VERSION = "candidate-review-notes-0.1"
MAX_BYTES = 512 * 1024
MAX_NOTES = 100
MAX_TEXT = 1000
# ECMAScript whitespace, explicitly fixed for cross-runtime text checks.
WHITESPACE = "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


class ReviewNotesError(ValueError):
    """A fixed diagnostic without note text, caller paths or metadata."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReviewNotesError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ReviewNotesError("Non-finite JSON value")


def _text(value: Any) -> bool:
    return (type(value) is str and 1 <= len(value) <= MAX_TEXT
            and bool(value.strip(WHITESPACE))
            and not any((ord(char) < 32 and char not in "\t\n")
                        or 127 <= ord(char) <= 159 or 0xd800 <= ord(char) <= 0xdfff
                        for char in value))


def load_review_notes(data: bytes, *, candidate: Any, project_id: str,
                      expected_fingerprint: str, transcript: Any) -> dict[str, Any]:
    """Decode bounded UTF-8 JSON and return independent, revision-bound notes.

    Only reference consistency is checked. A match proves neither media bytes,
    playback, authorship, review completion nor approval. No path is opened.
    """
    try:
        if type(data) is not bytes or not 1 <= len(data) <= MAX_BYTES:
            raise ReviewNotesError("Invalid notes input")
        selected = snapshot_candidate(candidate, project_id=project_id)
        revision = candidate_fingerprint(selected, project_id=project_id)
        if (selected["schema_version"] != TRANSCRIPT_SCHEMA_VERSION
                or type(expected_fingerprint) is not str or expected_fingerprint != revision):
            raise ReviewNotesError("Invalid selection")
        sidecar = transcripts.snapshot_transcript(transcript)
        audio = selected["audio"]
        transcripts.require_binding(sidecar, {"project_id": selected["project_id"],
            "content_id": selected["content_id"],
            "audio": {key: audio[key] for key in ("asset_id", "sha256", "duration_ms")}})
        transcript_revision = hashlib.sha256(transcripts.canonical_transcript_bytes(sidecar)).hexdigest()
        if (sidecar["language"] != selected["metadata"]["language"]
                or transcript_revision != selected["transcript"]["fingerprint"]):
            raise ReviewNotesError("Invalid transcript selection")
        document = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object,
                              parse_constant=_reject_constant)
        binding = {"schema_version": SCHEMA_VERSION, "project_id": selected["project_id"],
            "content_id": selected["content_id"], "candidate_fingerprint": revision,
            "transcript_fingerprint": transcript_revision}
        if (type(document) is not dict or set(document) != set(binding) | {"notes"}
                or any(type(document[key]) is not str or document[key] != value
                       for key, value in binding.items())):
            raise ReviewNotesError("Invalid notes binding")
        notes = document["notes"]
        if type(notes) is not list or len(notes) > MAX_NOTES:
            raise ReviewNotesError("Invalid notes count")
        for note in notes:
            if type(note) is not dict or set(note) != {"at_ms", "cue_id", "text"}:
                raise ReviewNotesError("Invalid note fields")
            at, cue_id = note["at_ms"], note["cue_id"]
            if (type(at) is not int or not 0 <= at <= audio["duration_ms"]
                    or (cue_id is not None and type(cue_id) is not str) or not _text(note["text"])):
                raise ReviewNotesError("Invalid note")
            expected_cue = next((cue["id"] for cue in sidecar["cues"]
                if cue["start_ms"] <= at < cue["end_ms"]), None)
            if cue_id != expected_cue:
                raise ReviewNotesError("Invalid note cue")
        return document
    except (CandidateError, transcripts.TranscriptError, ReviewNotesError,
            ValueError, TypeError, KeyError, RecursionError):
        raise ReviewNotesError("Review notes could not be validated") from None
