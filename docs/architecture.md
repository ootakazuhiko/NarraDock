# Architecture and manifest contract

## Separation

NarraDock has a shared core, replaceable adapters, a review interface, and a starter. A user's content, assets, settings, credentials, and runtime records live outside the shared repository. Voice, provider, theme, presenter, pose count, chapter count, and publication destination are not hard-coded defaults.

Audio-only: source -> audio preparation -> QA -> review -> local release package -> separately authorized transfer/publication.

Video-enabled: the same source/audio route plus visual planning, rendering, and video QA. Visual-only changes should not require audio regeneration. Runtime reuse and resume remain planned, not implemented.

## Bootstrap contract 0.1

The validator implementation in narradock.py is the current executable contract. Unknown or missing fields fail closed.

| Field | Meaning |
|---|---|
| schema_version | Exactly `0.1` |
| project_id / content_id | Lowercase alphanumeric, hyphen-separated identifiers, up to 64 characters |
| title | Nonempty trimmed text, up to 200 characters, no control/format characters |
| language | A restricted language-tag shape; not a complete BCP 47 registry validator |
| outputs | Nonempty distinct list containing `audio`, `video`, or both |
| source.kind | `existing_audio` or `script` |
| source.asset_id | Opaque identifier, not a path or URL |
| source.sha256 | Exactly 64 lowercase hexadecimal characters; structure only |
| publication.mode | Only `package_only` is accepted by this bootstrap |

A source asset ID resolves only in its project's future asset registry. Actual paths, credentials, voice profiles, rights evidence, and approval decisions are not fields of this public example contract. A valid SHA shape does not verify a source file or establish rights.

The planner fingerprints its own version and the canonical input. This identifies a proposal, not a build cache key or media checksum. Even output-list order affects the fingerprint. Planning creates no files and grants no approval. `unverified_requirements` always remain unverified in this version.

## Future contracts

Asset binding records, measured audio timelines, execution receipts, candidate-specific review decisions, allowlisted release manifests, and destination-specific publication receipts need independent schemas and tests. A publication authorization must bind project, candidate digest, metadata revision, destination, visibility, and timing. Unknown results require reconciliation rather than blind retry.
