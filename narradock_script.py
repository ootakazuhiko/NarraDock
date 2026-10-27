"""Separate explicitly typed private script blocks; no files, media or commands."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SCHEMA_VERSION = "script-blocks-0.1"
BODY_SCHEMA_VERSION = "script-body-0.1"
EXTRACTION_SCHEMA_VERSION = "script-extraction-0.1"
EXTRACTOR_VERSION = "body-directive-0.1"
TEXT_POLICY = "preserve-0.1"
MAX_BYTES = 1024 * 1024
MAX_RESULT_BYTES = 2 * 1024 * 1024
MAX_BLOCKS = 1000
MAX_TEXT = 4000
IDENTIFIER = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
LANGUAGE = re.compile(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*")
WHITESPACE = "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
ERROR = "Script could not be validated"


class ScriptError(ValueError):
    """Fixed diagnostics without script text, caller paths or supplied values."""


def _fields(value: Any, fields: set[str]) -> None:
    if (type(value) is not dict or len(value) != len(fields)
            or any(type(key) is not str for key in value) or set(value) != fields):
        raise ScriptError(ERROR)


def _identifier(value: Any) -> bool:
    return type(value) is str and 1 <= len(value) <= 64 and IDENTIFIER.fullmatch(value) is not None


def _text(value: Any) -> bool:
    return (type(value) is str and 1 <= len(value) <= MAX_TEXT and bool(value.strip(WHITESPACE))
            and not any((ord(char) < 32 and char not in "\t\n\r")
                        or 127 <= ord(char) <= 159 or 0xd800 <= ord(char) <= 0xdfff
                        for char in value))


def _canonical_bytes(document: dict, limit: int) -> bytes:
    result = bytearray()
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    for part in encoder.iterencode(document):
        encoded = part.encode("utf-8")
        if len(result) + len(encoded) > limit:
            raise ScriptError(ERROR)
        result.extend(encoded)
    return bytes(result)


def _snapshot(document: Any, project_id: str) -> dict:
    _fields(document, {"schema_version", "project_id", "content_id", "language", "blocks"})
    schema, project, content = document["schema_version"], document["project_id"], document["content_id"]
    language, blocks = document["language"], document["blocks"]
    if type(schema) is not str or schema != SCHEMA_VERSION:
        raise ScriptError(ERROR)
    if not all(_identifier(value) for value in (project_id, project, content)) or project != project_id:
        raise ScriptError(ERROR)
    if type(language) is not str or len(language) > 20 or LANGUAGE.fullmatch(language) is None:
        raise ScriptError(ERROR)
    if type(blocks) is not list or not 1 <= len(blocks) <= MAX_BLOCKS:
        raise ScriptError(ERROR)
    # Bound the copy even if another caller thread appends while it is being read.
    entries = blocks[:MAX_BLOCKS + 1]
    if not 1 <= len(entries) <= MAX_BLOCKS:
        raise ScriptError(ERROR)
    copied, identifiers = [], set()
    text_bytes, body_count = 0, 0
    for block in entries:
        _fields(block, {"id", "kind", "text"})
        identifier, kind, text = block["id"], block["kind"], block["text"]
        if (not _identifier(identifier) or identifier in identifiers
                or type(kind) is not str or kind not in {"body", "directive"} or not _text(text)):
            raise ScriptError(ERROR)
        text_bytes += len(text.encode("utf-8"))
        if text_bytes > MAX_BYTES:
            raise ScriptError(ERROR)
        identifiers.add(identifier)
        body_count += kind == "body"
        copied.append({"id": identifier, "kind": kind, "text": text})
    if not body_count:
        raise ScriptError(ERROR)
    snapshot = {"schema_version": schema, "project_id": project, "content_id": content,
                "language": language, "blocks": copied}
    _canonical_bytes(snapshot, MAX_BYTES)
    return snapshot


def snapshot_script(document: Any, *, project_id: str) -> dict:
    """Return an independent bounded copy of a strictly typed script document."""
    try:
        return _snapshot(document, project_id)
    except (ValueError, TypeError, KeyError, RuntimeError, RecursionError):
        raise ScriptError(ERROR) from None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ScriptError(ERROR)
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ScriptError(ERROR)


def load_script(data: bytes, *, project_id: str) -> dict:
    """Parse bounded UTF-8 JSON bytes, without opening paths or running directives."""
    try:
        if type(data) is not bytes or not 1 <= len(data) <= MAX_BYTES:
            raise ScriptError(ERROR)
        document = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object,
                              parse_constant=_reject_constant)
        return _snapshot(document, project_id)
    except (ValueError, TypeError, KeyError, RuntimeError, RecursionError):
        raise ScriptError(ERROR) from None


def script_fingerprint(document: Any, *, project_id: str) -> str:
    """Hash the full canonical script, including directives; not a raw-file hash."""
    try:
        snapshot = _snapshot(document, project_id)
        return hashlib.sha256(_canonical_bytes(snapshot, MAX_BYTES)).hexdigest()
    except (ValueError, TypeError, KeyError, RuntimeError, RecursionError):
        raise ScriptError(ERROR) from None


def extract_script(document: Any, *, project_id: str, expected_fingerprint: str) -> dict:
    """Extract the explicitly selected script revision into private structured data.

    Body text is never joined, normalized or inferred from words. Separate body
    identity supports later comparison; this API does not invalidate or approve
    media, decide speech input, interpret directives, or schedule regeneration.
    """
    try:
        if type(expected_fingerprint) is not str or re.fullmatch(r"[0-9a-f]{64}", expected_fingerprint) is None:
            raise ScriptError(ERROR)
        snapshot = _snapshot(document, project_id)
        revision = hashlib.sha256(_canonical_bytes(snapshot, MAX_BYTES)).hexdigest()
        if revision != expected_fingerprint:
            raise ScriptError(ERROR)
        scope = {key: snapshot[key] for key in ("project_id", "content_id", "language")}
        body, directives, projection = [], [], []
        for index, block in enumerate(snapshot["blocks"]):
            item = {"id": block["id"], "text": block["text"]}
            if block["kind"] == "body":
                encoded = block["text"].encode("utf-8")
                projection.append(item)
                body.append({**item, "size_bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest()})
            else:
                directives.append({**item, "source_index": index})
        # Source indices and the full revision must not invalidate body identity
        # when only directives change. IDs and body order remain significant.
        body_document = {"schema_version": BODY_SCHEMA_VERSION, **scope,
                         "text_policy": TEXT_POLICY, "blocks": projection}
        body_revision = hashlib.sha256(_canonical_bytes(body_document, MAX_BYTES)).hexdigest()
        result = {"schema_version": EXTRACTION_SCHEMA_VERSION, **scope,
                  "extractor_version": EXTRACTOR_VERSION, "text_policy": TEXT_POLICY,
                  "script_fingerprint": revision, "body_fingerprint": body_revision,
                  "body_block_count": len(body), "body_blocks": body,
                  "directive_block_count": len(directives), "directives": directives}
        _canonical_bytes(result, MAX_RESULT_BYTES)
        return result
    except (ValueError, TypeError, KeyError, RuntimeError, RecursionError):
        raise ScriptError(ERROR) from None
