"""Create an offline, candidate-bound audio ZIP in a trusted private directory."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
import zipfile

from narradock_assets import AssetError, CHUNK_BYTES, copy_verified_asset
from narradock_candidates import (CandidateError, candidate_fingerprint, snapshot_candidate,
                                 TRANSCRIPT_SCHEMA_VERSION as TRANSCRIPT_CANDIDATE_VERSION)
import narradock_transcript as transcripts

SCHEMA_VERSION = "audio-package-0.1"
TRANSCRIPT_SCHEMA_VERSION = "audio-package-0.2"
DECISIONS_VERSION = "audio-package-decisions-0.1"
MAX_WEBVTT_BYTES = 5 * transcripts.MAX_BYTES
IDENTIFIER = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")


class PackageError(ValueError):
    """A fixed diagnostic without paths, metadata or private decision references."""


def _canonical(document: dict[str, Any]) -> bytes:
    return json.dumps(document, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _fields(value: Any, fields: set[str]) -> None:
    if type(value) is not dict or len(value) != len(fields) or set(value) != fields:
        raise PackageError("Invalid package decision fields")


def _identifier(value: Any) -> bool:
    return (type(value) is str and 0 < len(value) <= 64
            and IDENTIFIER.fullmatch(value) is not None)


def _decisions(document: Any, project_id: str, fingerprint: str) -> dict[str, Any]:
    """Snapshot assertions from the trusted caller, not proof of their authority."""
    try:
        _fields(document, {"schema_version", "project_id", "candidate_fingerprint",
                           "decision_id", "rights", "technical_qa", "human_review",
                           "local_packaging"})
        schema, project, selected, decision = (document["schema_version"], document["project_id"],
                                              document["candidate_fingerprint"], document["decision_id"])
        if (type(schema) is not str or schema != DECISIONS_VERSION
                or type(project) is not str or project != project_id
                or type(selected) is not str or selected != fingerprint
                or not _identifier(decision)):
            raise PackageError("Package decisions do not match the selected candidate")
        snapshot = {"schema_version": schema, "project_id": project,
                    "candidate_fingerprint": selected, "decision_id": decision}
        for name, references in (("rights", {"evidence_id"}),
                                 ("technical_qa", {"evidence_id"}),
                                 ("human_review", {"evidence_id", "reviewer_id"}),
                                 ("local_packaging", {"authority_id"})):
            record = document[name]
            _fields(record, {"status"} | references)
            status = record["status"]
            values = {key: record[key] for key in references}
            if type(status) is not str or status != "approved" or not all(
                    _identifier(value) for value in values.values()):
                raise PackageError("Required package decision is missing or unapproved")
            snapshot[name] = {"status": status, **values}
        return snapshot
    except PackageError:
        raise
    except (KeyError, TypeError, ValueError, RuntimeError):
        raise PackageError("Package decisions could not be validated") from None


def _output_directory(directory: Path, project_root: Path) -> Path:
    directory, project_root = Path(directory), Path(project_root)
    if any(not path.is_absolute() or ".." in path.parts for path in (directory, project_root)):
        raise PackageError("Absolute trusted local directories are required")
    if os.name == "nt" and any(not re.fullmatch(r"[A-Za-z]:", path.drive)
                               for path in (directory, project_root)):
        raise PackageError("Local drive directories are required")
    output, source = directory.resolve(strict=True), project_root.resolve(strict=True)
    if os.name == "nt" and any(not re.fullmatch(r"[A-Za-z]:", path.drive)
                               for path in (output, source)):
        raise PackageError("Local drive directories are required")
    if not output.is_dir() or output == source or source in output.parents:
        raise PackageError("Output must be a separate trusted private directory")
    return output


def _entry(name: str) -> zipfile.ZipInfo:
    entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_STORED
    entry.create_system = 3
    entry.external_attr = 0o100600 << 16
    return entry


def _file_record(data: bytes) -> dict[str, Any]:
    return {"size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _transcript_payloads(candidate: dict[str, Any], document: Any) -> dict[str, bytes]:
    if candidate["schema_version"] != TRANSCRIPT_CANDIDATE_VERSION:
        if document is not None:
            raise PackageError("Audio-only candidates do not accept a transcript")
        return {}
    snapshot = transcripts.snapshot_transcript(document)
    audio = candidate["audio"]
    transcripts.require_binding(snapshot, {"project_id": candidate["project_id"],
        "content_id": candidate["content_id"],
        "audio": {key: audio[key] for key in ("asset_id", "sha256", "duration_ms")}})
    if snapshot["language"] != candidate["metadata"]["language"]:
        raise PackageError("Transcript language does not match the candidate")
    # Bound serialization before calling the legacy in-memory fingerprint/export APIs.
    canonical = transcripts.canonical_transcript_bytes(snapshot)
    if transcripts.fingerprint(snapshot) != candidate["transcript"]["fingerprint"]:
        raise PackageError("Transcript fingerprint mismatch")
    webvtt = transcripts.to_webvtt(snapshot).encode("utf-8")
    if len(webvtt) > MAX_WEBVTT_BYTES:
        raise PackageError("Transcript exceeds WebVTT size limit")
    return {"transcript.json": canonical, "transcript.vtt": webvtt}


def create_audio_package(document: Any, *, project_id: str, expected_fingerprint: str,
                         decisions: Any, registry: Any, project_root: Path,
                         output_directory: Path, transcript: Any = None) -> dict[str, Any]:
    """Create <candidate fingerprint>.zip exclusively, with no external transfer.

    The caller must authenticate and check current decisions, and own the private
    output directory and ancestors with no concurrent writer. Only a completed,
    verified staging file is linked to the final name; no existing path is replaced.
    Hard-link support is required. This is not an OS sandbox or a revocation service.
    """
    staging = final = None
    linked = completed = False
    try:
        candidate = snapshot_candidate(document, project_id=project_id)
        fingerprint = candidate_fingerprint(candidate, project_id=project_id)
        if type(expected_fingerprint) is not str or expected_fingerprint != fingerprint:
            raise PackageError("Candidate fingerprint mismatch")
        decision_snapshot = _decisions(decisions, project_id, fingerprint)
        decision_fingerprint = hashlib.sha256(_canonical(decision_snapshot)).hexdigest()
        sidecars = _transcript_payloads(candidate, transcript)
        # Candidate/decision/transcript gates precede source and output filesystem I/O.
        directory = _output_directory(output_directory, project_root)
        final = directory / (fingerprint + ".zip")
        descriptor, staging_name = tempfile.mkstemp(prefix=".narradock-", suffix=".tmp", dir=directory)
        staging = Path(staging_name)
        try:
            stream = os.fdopen(descriptor, "w+b")
        except BaseException:
            os.close(descriptor)
            raise
        with stream:
            with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_STORED) as archive:
                audio = candidate["audio"]
                with archive.open(_entry("audio.bin"), mode="w", force_zip64=True) as destination:
                    measured = copy_verified_asset(registry, project_root=project_root,
                        project_id=project_id, asset_id=audio["asset_id"], destination=destination)
                if any(measured[key] != audio[key] for key in ("sha256", "size_bytes")):
                    raise PackageError("Candidate asset declaration mismatch")
                metadata = _canonical(candidate)
                archive.writestr(_entry("candidate.json"), metadata)
                for member, data in sidecars.items():
                    archive.writestr(_entry(member), data)
                manifest = {"schema_version": TRANSCRIPT_SCHEMA_VERSION if sidecars else SCHEMA_VERSION,
                            "project_id": project_id,
                            "content_id": candidate["content_id"], "candidate_fingerprint": fingerprint,
                            "files": {"audio.bin": {key: measured[key] for key in ("size_bytes", "sha256")},
                                      "candidate.json": _file_record(metadata)}}
                manifest["files"].update({member: _file_record(data) for member, data in sidecars.items()})
                archive.writestr(_entry("manifest.json"), _canonical(manifest))
            stream.flush()
            os.fsync(stream.fileno())
            stream.seek(0)
            digest, size = hashlib.sha256(), 0
            expected_size = os.fstat(stream.fileno()).st_size
            while size <= expected_size:
                chunk = stream.read(min(CHUNK_BYTES, expected_size + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
            if size != expected_size or os.fstat(stream.fileno()).st_size != expected_size:
                raise PackageError("Package changed during final verification")
        # Atomic exclusive name creation on supported local filesystems. Unlike
        # rename/replace this never clobbers an existing file or empty directory.
        os.link(staging, final)
        linked = True
        staging.unlink()
        staging = None
        completed = True
        return {"packaged": True, "scope": "local_audio_package_only",
                "project_id": project_id, "content_id": candidate["content_id"],
                "candidate_fingerprint": fingerprint, "decisions_bound": True,
                "decisions_fingerprint": decision_fingerprint,
                "package": {"size_bytes": size, "sha256": digest.hexdigest()},
                "rights_verified": False, "media_qa_passed": False,
                "external_transfer": False, "publication": False}
    except PackageError:
        raise
    except (AssetError, CandidateError, transcripts.TranscriptError,
            OSError, ValueError, TypeError, RuntimeError):
        raise PackageError("Local audio package could not be created") from None
    finally:
        if not completed:
            cleanup_failed = False
            for owned in (final if linked else None, staging):
                if owned is not None:
                    try:
                        owned.unlink()
                    except OSError:
                        cleanup_failed = True
            if cleanup_failed:
                raise PackageError("Failed package output could not be removed") from None
