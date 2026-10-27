# Explicit body and directive blocks

`narradock_script.py` separates caller-marked body text from production directives
without interpreting either. It is an offline Python API using the standard
library. It opens no files, runs no commands, calls no provider and generates no
media. The caller decides which blocks are body; words such as “BGM” or “change
the screen” do not cause text to be removed or reclassified.

This is a standalone contract. The foundation manifest, audio candidate,
transcript, package and review-note schemas are unchanged. In particular,
`source.kind: script` remains a symbolic plan input: it does not invoke this API
or synthesize speech. Selecting text for an actual speech engine is a later
adapter decision.

## Input: `script-blocks-0.1`

The root has exactly `schema_version`, `project_id`, `content_id`, `language` and
`blocks`. Each block has exactly `id`, `kind` and `text`. `kind` is either `body`
or `directive`. The mixed array preserves source order, with at least one body
block and globally unique IDs across both kinds. No unknown fields or kinds are
accepted. See the [neutral example](../examples/script-contract.json).

Project/content/block IDs are at most 64 ASCII characters: a lowercase letter
followed by lowercase letters/digits, with single hyphens separating nonempty
groups. Language is at most 20 characters and follows the restricted shape
`[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*`; this is not complete BCP 47 validation.
The caller's assigned project ID must match the document.

The fixed `preserve-0.1` text policy keeps text exactly as supplied: leading and
trailing spaces, tabs, LF, CR, CRLF, combining characters, Unicode format
characters and valid emoji sequences are preserved. No trimming, newline
conversion, Unicode normalization, concatenation or separator insertion occurs.
Empty or whitespace-only text is rejected for either kind. Whitespace-only
checking uses the fixed ECMAScript whitespace set, including U+FEFF. Other C0
controls besides tab/LF/CR, C1 controls (U+007F–U+009F) and lone surrogates are
rejected. Directive text is opaque data, never an instruction to this API.

## API and selection

```python
from narradock_script import load_script, script_fingerprint, extract_script

document = load_script(json_bytes, project_id=assigned_project_id)
revision = script_fingerprint(document, project_id=assigned_project_id)

# Later, pass the revision retained when the caller selected this script.
result = extract_script(
    document,
    project_id=assigned_project_id,
    expected_fingerprint=selected_script_fingerprint,
)
```

`load_script` accepts exact built-in `bytes`, bounds them before decoding UTF-8,
and rejects BOM, malformed JSON, duplicate keys at any level, NaN/Infinity,
unknown fields and wrong types. `snapshot_script(document, project_id=...)`
validates in-memory input and returns an independent copy. Dictionaries, lists
and strings must be exact built-in types; custom copy/access hooks are not used.
The caller owns bounded source reading and any explicit private persistence.

`script_fingerprint` and `extract_script` independently snapshot their input.
The caller must provide a previously selected full fingerprint to extract;
any change, including directive-only edits, rejects that stale selection. A
caller can deliberately select the updated revision and extract it again.
The snapshots are independent copies, not a synchronization mechanism for
concurrently changing caller data.

Failure raises `ScriptError` with `Script could not be validated`, without
supplied text, paths, values or a partial result. This validates declared scope
and selected revision consistency; it does not authenticate the caller or author.

## Result: `script-extraction-0.1`

| Field | Meaning |
|---|---|
| `schema_version` | `script-extraction-0.1` |
| `project_id`, `content_id`, `language` | Selected script scope |
| `extractor_version` | `body-directive-0.1` |
| `text_policy` | `preserve-0.1` |
| `script_fingerprint` | SHA-256 of the complete canonical input document |
| `body_fingerprint` | SHA-256 of the body projection described below |
| `body_block_count`, `body_blocks` | Ordered body count and records containing `id`, `text`, `size_bytes`, `sha256` |
| `directive_block_count`, `directives` | Ordered directive count and records containing `id`, `text`, `source_index` |

Each body block's `size_bytes` and `sha256` cover **only its exact UTF-8 text
bytes**, without an added BOM or separator. An existing U+FEFF in text is
preserved and hashed. These block digests do not cover ID, order or scope.
Identical text in two blocks legitimately has the same block digest. Body
records remain separate, so `['ab', 'c']` and `['a', 'bc']` have distinct body
fingerprints even though naive concatenation would produce the same text.

Directive `source_index` is its zero-based position in the original mixed
`blocks` array. IDs and relative body order are preserved. No directive is
executed, assigned to a renderer or silently discarded.

Canonical JSON uses UTF-8, sorted object keys, compact `,`/`:` separators,
`ensure_ascii=False` and no trailing newline. Array order and text content are
significant. JSON key order, exterior whitespace and equivalent JSON escapes
do not change the full fingerprint. This is **not the original JSON file's byte
hash** and must not replace an asset or manifest `source.sha256` byte reference.

The body projection contains exactly:

```text
schema_version: "script-body-0.1"
project_id, content_id, language: selected scope
text_policy: "preserve-0.1"
blocks: body-only [{id, text}, ...] in original relative order
```

Its canonical bytes are hashed independently. The full script fingerprint,
directives, source indices and derived per-block digests are excluded. Changing
body text, ID, order, count, scope, language or text policy changes body identity;
inserting, moving, deleting or editing directives alone preserves it while
changing full script identity. No media invalidation or regeneration is scheduled.

**Matching body identity does not prove that media can be reused.** Directives
may describe voice, pacing, pronunciation, mixing or visual changes that affect
output despite identical body text. A future adapter must include its effective
settings, tool version and dependencies in its own identity and review rules.
Neither fingerprint establishes rights, playback quality, human approval or
publication authority.

## Limits and validation

| Input/output | Limit, including equality |
|---|---|
| Raw UTF-8 JSON input | 1 MiB, including JSON formatting |
| Canonical script and body projection | 1 MiB each |
| Mixed blocks | 1–1,000, with at least one body block |
| Text in each block | 1–4,000 Unicode code points |
| Canonical extraction result | 2 MiB |

The result limit applies to canonical UTF-8 JSON as defined above; caller-chosen
pretty printing or ASCII escaping can produce a larger serialization. In-memory
validation also bounds accumulated text bytes before canonical encoding. These
are payload limits, not a process-memory or CPU guarantee.

Results contain the private body and directive text. They are not sanitized
distribution artifacts; keep real inputs, extracted text and fingerprints in the
assigned private workspace. A downstream renderer must use a safe text sink.
The example and tests use only newly authored neutral text.

The discovered Python suite tests exact schema/types, JSON/Unicode/size bounds,
fixed revision vectors, text preservation, directive-only versus body changes,
scope/selection rejection, source/output independence and absence of file or
command execution. Existing Linux/Windows CI discovers these tests without a
workflow or dependency change. No browser UI, speech-engine integration, real
script acceptance or media generation is implemented or claimed by this unit.
