"""NarraDock's offline manifest validator and symbolic planner (no execution)."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

VERSION = "0.1.0a1"
MAX_BYTES = 131072
IDENTIFIER = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")


class ManifestError(ValueError):
    """Invalid input; messages intentionally exclude supplied values."""


def _object(value: Any, keys: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise ManifestError(f"Invalid {label} fields")


def _text(value: Any, limit: int) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= limit
            and value == value.strip()
            and not any(unicodedata.category(c).startswith("C") for c in value))


def validate(manifest: Any) -> None:
    """Validate structure only; does not resolve assets or verify their hashes."""
    _object(manifest, {"schema_version", "project_id", "content_id", "title",
                       "language", "outputs", "source", "publication"}, "manifest")
    if manifest["schema_version"] != "0.1":
        raise ManifestError("Unsupported schema version")
    for key in ("project_id", "content_id"):
        value = manifest[key]
        if not _text(value, 64) or not IDENTIFIER.fullmatch(value):
            raise ManifestError("Invalid identifier")
    if not _text(manifest["title"], 200):
        raise ManifestError("Invalid title")
    language = manifest["language"]
    if not _text(language, 20) or not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", language):
        raise ManifestError("Unsupported language tag shape")
    outputs = manifest["outputs"]
    if (not isinstance(outputs, list) or not outputs
            or any(not isinstance(v, str) or v not in ("audio", "video") for v in outputs)
            or len(set(outputs)) != len(outputs)):
        raise ManifestError("Invalid outputs")
    source = manifest["source"]
    _object(source, {"kind", "asset_id", "sha256"}, "source")
    if source["kind"] not in ("existing_audio", "script"):
        raise ManifestError("Unsupported source kind")
    if not _text(source["asset_id"], 64) or not IDENTIFIER.fullmatch(source["asset_id"]):
        raise ManifestError("Invalid asset identifier")
    if not isinstance(source["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"]):
        raise ManifestError("Invalid source digest")
    _object(manifest["publication"], {"mode"}, "publication")
    if manifest["publication"]["mode"] != "package_only":
        raise ManifestError("Only package_only planning is supported")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError("Duplicate JSON key")
        result[key] = value
    return result


def load_manifest(path: Path) -> dict[str, Any]:
    """Read only the explicitly supplied JSON file, with a bounded read."""
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ManifestError("Manifest exceeds size limit")
        manifest = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
        validate(manifest)
        return manifest
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ManifestError("Manifest could not be read as valid UTF-8 JSON") from error


def plan(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic proposal, never an executable or approved job."""
    validate(manifest)
    canonical = json.dumps({"planner": VERSION, "manifest": manifest},
                           ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    steps = ["resolve_source", "verify_source_hash", "review_content"]
    requirements = ["asset_binding", "rights_review", "candidate_review"]
    if manifest["source"]["kind"] == "script":
        steps.append("synthesize_audio")
        requirements += ["voice_profile", "generation_authorization"]
    steps.append("audio_qa")
    if "video" in manifest["outputs"]:
        steps += ["render_video", "video_qa"]
        requirements.append("visual_profile")
    steps += ["review_candidate", "prepare_local_package"]
    return {"planner_version": VERSION, "status": "plan_only",
            "plan_fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "project_id": manifest["project_id"], "content_id": manifest["content_id"],
            "steps": steps, "unverified_requirements": requirements,
            "executes_steps": False, "external_transfer": False, "publication": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "plan"))
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        result = {"valid": True, "scope": "structure_only"} if args.command == "validate" else plan(manifest)
    except ManifestError as error:
        print(f"Invalid manifest: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
