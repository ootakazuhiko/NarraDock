"""Identify an audio candidate and check its selected asset's current bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, BinaryIO
import unicodedata

from narradock_assets import AssetError, MAX_ASSET_BYTES, load_registry, verify_asset

SCHEMA_VERSION = "audio-candidate-0.1"
MAX_CANDIDATE_BYTES = 64 * 1024
MAX_TEXT_LENGTH = 200
MAX_CREDITS = 16
READ_CHUNK_BYTES = 4096
IDENTIFIER = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
DIGEST = re.compile(r"[0-9a-f]{64}")
LANGUAGE = re.compile(r"[a-z]{2,3}(?:-[A-Z]{2})?")


class CandidateError(ValueError):
    """A fixed diagnostic without supplied metadata, file paths or I/O details."""


def _fields(value: Any, fields: set[str]) -> None:
    if type(value) is not dict or len(value) != len(fields) or set(value) != fields:
        raise CandidateError("Invalid candidate fields")


def _identifier(value: Any) -> bool:
    return (type(value) is str and 0 < len(value) <= 64
            and IDENTIFIER.fullmatch(value) is not None)


def _digest(value: Any) -> bool:
    return type(value) is str and DIGEST.fullmatch(value) is not None


def _text(value: Any) -> bool:
    return (type(value) is str and 0 < len(value) <= MAX_TEXT_LENGTH and bool(value.strip())
            and not any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
                        for char in value))


def _snapshot(document: Any, project_id: str) -> dict[str, Any]:
    """Copy validated primitive fields; callers cannot mutate this revision later."""
    try:
        _fields(document, {"schema_version", "project_id", "content_id", "audio", "metadata"})
        schema, project, content = (document["schema_version"], document["project_id"],
                                    document["content_id"])
        audio, metadata = document["audio"], document["metadata"]
        _fields(audio, {"asset_id", "size_bytes", "sha256"})
        _fields(metadata, {"title", "language", "credits"})
        asset, size, digest = audio["asset_id"], audio["size_bytes"], audio["sha256"]
        title, language, credits = metadata["title"], metadata["language"], metadata["credits"]
        if type(schema) is not str or schema != SCHEMA_VERSION:
            raise CandidateError("Unsupported candidate schema")
        if not all(_identifier(value) for value in (project_id, project, content, asset)):
            raise CandidateError("Invalid candidate identifier")
        if project != project_id:
            raise CandidateError("Candidate project mismatch")
        if type(size) is not int or not 0 <= size <= MAX_ASSET_BYTES or not _digest(digest):
            raise CandidateError("Invalid candidate asset declaration")
        if not _text(title) or type(language) is not str or LANGUAGE.fullmatch(language) is None:
            raise CandidateError("Invalid candidate metadata")
        if type(credits) is not list or not 0 <= len(credits) <= MAX_CREDITS:
            raise CandidateError("Invalid candidate credits")
        credits = credits.copy()
        if (len(credits) > MAX_CREDITS or not all(_text(credit) for credit in credits)
                or len(set(credits)) != len(credits)):
            raise CandidateError("Invalid candidate credits")
        return {"schema_version": schema, "project_id": project, "content_id": content,
                "audio": {"asset_id": asset, "size_bytes": size, "sha256": digest},
                "metadata": {"title": title, "language": language, "credits": credits}}
    except CandidateError:
        raise
    except (KeyError, TypeError, ValueError, RuntimeError):
        raise CandidateError("Candidate could not be validated") from None


def validate_candidate(document: Any, *, project_id: str) -> None:
    """Validate structure and project assignment only; no asset is read."""
    _snapshot(document, project_id)


def snapshot_candidate(document: Any, *, project_id: str) -> dict[str, Any]:
    """Return an independent validated revision for downstream consumers."""
    return _snapshot(document, project_id)


def _fingerprint(snapshot: dict[str, Any]) -> str:
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def candidate_fingerprint(document: Any, *, project_id: str) -> str:
    """Identify all declared fields; a fingerprint does not certify their bytes."""
    return _fingerprint(_snapshot(document, project_id))


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise CandidateError("Duplicate candidate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise CandidateError("Non-finite candidate JSON value")


def load_candidate(source: BinaryIO, *, project_id: str) -> dict[str, Any]:
    """Read bounded UTF-8 JSON from a caller-owned binary stream; never open a path."""
    try:
        data = bytearray()
        while len(data) <= MAX_CANDIDATE_BYTES:
            size = min(READ_CHUNK_BYTES, MAX_CANDIDATE_BYTES + 1 - len(data))
            chunk = source.read(size)
            if type(chunk) is not bytes or len(chunk) > size:
                raise CandidateError("Invalid candidate input stream")
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > MAX_CANDIDATE_BYTES:
            raise CandidateError("Candidate exceeds size limit")
        document = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object,
                              parse_constant=_reject_constant)
        return _snapshot(document, project_id)
    except CandidateError:
        raise
    except (OSError, ValueError, TypeError, RecursionError):
        raise CandidateError("Candidate could not be read as valid UTF-8 JSON") from None


def verify_candidate_asset(document: Any, *, project_id: str, expected_fingerprint: str,
                           registry: Any, project_root: Path) -> dict[str, Any]:
    """Bind a caller-selected revision to a fresh observation of its asset bytes."""
    snapshot = _snapshot(document, project_id)
    fingerprint = _fingerprint(snapshot)
    if not _digest(expected_fingerprint) or fingerprint != expected_fingerprint:
        raise CandidateError("Candidate fingerprint mismatch")
    audio = snapshot["audio"]
    try:
        measured = verify_asset(registry, project_root=project_root,
                                project_id=project_id, asset_id=audio["asset_id"])
    except AssetError:
        raise CandidateError("Candidate asset could not be verified") from None
    if measured["sha256"] != audio["sha256"] or measured["size_bytes"] != audio["size_bytes"]:
        raise CandidateError("Candidate asset declaration mismatch")
    return {"verified": True, "scope": "candidate_asset_bytes_only",
            "candidate_fingerprint": fingerprint, "project_id": snapshot["project_id"],
            "content_id": snapshot["content_id"],
            "audio": {"asset_id": audio["asset_id"], "sha256": measured["sha256"],
                      "size_bytes": measured["size_bytes"]},
            "rights_verified": False, "media_qa_passed": False, "human_reviewed": False,
            "packaged": False, "external_transfer": False, "publication": False}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CandidateError("Invalid command arguments")


def main(argv: list[str] | None = None) -> int:
    try:
        parser = _Parser(description=__doc__ + " Candidate JSON is read from stdin.")
        parser.add_argument("command", choices=("validate", "verify"))
        parser.add_argument("--project-id", required=True)
        parser.add_argument("--expected-fingerprint")
        parser.add_argument("--registry", type=Path)
        parser.add_argument("--project-root", type=Path)
        args = parser.parse_args(argv)
        verification_args = (args.expected_fingerprint, args.registry, args.project_root)
        if args.command == "verify" and any(value is None for value in verification_args):
            raise CandidateError("Verification requires fingerprint, registry and project root")
        if args.command == "validate" and any(value is not None for value in verification_args):
            raise CandidateError("Structural validation does not accept verification arguments")
        document = load_candidate(sys.stdin.buffer, project_id=args.project_id)
        if args.command == "verify":
            # Reject a stale selection before even reading the supplied registry.
            if (not _digest(args.expected_fingerprint)
                    or candidate_fingerprint(document, project_id=args.project_id)
                    != args.expected_fingerprint):
                raise CandidateError("Candidate fingerprint mismatch")
            registry = load_registry(args.registry, project_id=args.project_id)
            result = verify_candidate_asset(document, project_id=args.project_id,
                expected_fingerprint=args.expected_fingerprint, registry=registry,
                project_root=args.project_root)
        else:
            result = {"valid": True, "scope": "candidate_structure_only", "bytes_verified": False,
                      "candidate_fingerprint": candidate_fingerprint(document, project_id=args.project_id),
                      "external_transfer": False, "publication": False}
        sys.stdout.write(json.dumps(result, sort_keys=True, indent=2) + "\n")
        sys.stdout.flush()
    except AssetError:
        print("Invalid candidate: Registry could not be loaded", file=sys.stderr)
        return 2
    except CandidateError as error:
        print(f"Invalid candidate: {error}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError):
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())
        print("Invalid candidate: Output could not be written", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
