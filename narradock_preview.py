"""Build a private, candidate-bound audio preview; do not write or publish it."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from narradock_audio import AudioMeasurementError, MAX_CAPTURE_BYTES, read_candidate_wav
from narradock_candidates import (CandidateError, TRANSCRIPT_SCHEMA_VERSION,
                                 candidate_fingerprint, snapshot_candidate)
import narradock_player as player
import narradock_transcript as transcripts

SCHEMA_VERSION = "candidate-audio-preview-0.1"
MAX_PREVIEW_CUES = 1000
MAX_ESCAPED_TRANSCRIPT_BYTES = 8 * 1024 * 1024
MAX_HTML_BYTES = 64 * 1024 * 1024


class PreviewError(ValueError):
    """A fixed diagnostic without caller text, source paths or operational data."""


def build_candidate_preview(document: Any, *, project_id: str, expected_fingerprint: str,
                            transcript: Any, registry: Any,
                            project_root: Path) -> tuple[bytes, dict[str, Any]]:
    """Return UTF-8 HTML bytes and a receipt after selection and byte verification.

    The trusted caller owns the private result and any explicit persistence. No
    approval record is required or created. WAV metadata is copied unchanged.
    """
    try:
        candidate = snapshot_candidate(document, project_id=project_id)
        revision = candidate_fingerprint(candidate, project_id=project_id)
        if (candidate["schema_version"] != TRANSCRIPT_SCHEMA_VERSION
                or type(expected_fingerprint) is not str or expected_fingerprint != revision):
            raise PreviewError("Invalid preview selection")
        audio = candidate["audio"]
        if not 46 <= audio["size_bytes"] <= MAX_CAPTURE_BYTES:
            raise PreviewError("Preview audio exceeds limit")
        sidecar = transcripts.snapshot_transcript(transcript)
        if len(sidecar["cues"]) > MAX_PREVIEW_CUES:
            raise PreviewError("Preview cue count exceeds limit")
        transcripts.require_binding(sidecar, {"project_id": candidate["project_id"],
            "content_id": candidate["content_id"],
            "audio": {key: audio[key] for key in ("asset_id", "sha256", "duration_ms")}})
        canonical = transcripts.canonical_transcript_bytes(sidecar)
        transcript_revision = hashlib.sha256(canonical).hexdigest()
        if (sidecar["language"] != candidate["metadata"]["language"]
                or transcript_revision != candidate["transcript"]["fingerprint"]):
            raise PreviewError("Preview transcript mismatch")
        payload = player._json_for_html(sidecar)
        payload_size = len(payload.encode("utf-8"))
        if payload_size > MAX_ESCAPED_TRANSCRIPT_BYTES:
            raise PreviewError("Preview transcript exceeds escaped limit")
        if payload_size + 4 * ((audio["size_bytes"] + 2) // 3) > MAX_HTML_BYTES:
            raise PreviewError("Preview payload exceeds HTML limit")
        # All candidate/sidecar gates precede asset I/O. Captured and measured
        # bytes come from a single guarded read, never a reopened source path.
        wav, measurements = read_candidate_wav(candidate, project_id=project_id,
            expected_fingerprint=revision, registry=registry, project_root=project_root)
        if measurements["duration"]["matches_declared"] is not True:
            raise PreviewError("Preview duration mismatch")
        output = player._render_page(sidecar, wav, candidate=candidate, revision=revision,
                                     payload=payload, max_bytes=MAX_HTML_BYTES)
    except (CandidateError, AudioMeasurementError, transcripts.TranscriptError,
            PreviewError, OSError, ValueError, TypeError, RecursionError):
        raise PreviewError("Candidate audio preview could not be created") from None

    return output, {"schema_version": SCHEMA_VERSION, "preview_created": True,
        "scope": "candidate_local_preview_only", "candidate_fingerprint": revision,
        "transcript_fingerprint": transcript_revision, "project_id": candidate["project_id"],
        "content_id": candidate["content_id"], "measurements": measurements,
        "html": {"size_bytes": len(output), "sha256": hashlib.sha256(output).hexdigest()},
        "rights_verified": False, "media_qa_passed": False, "human_reviewed": False,
        "transcript_alignment_verified": False, "packaged": False,
        "external_transfer": False, "publication": False}
