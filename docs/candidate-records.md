# Audio candidate records 0.1 and 0.2

An audio candidate binds one declared audio asset and its delivery metadata to a
content fingerprint. `narradock_candidates.py` validates that record and can
compare the caller-selected revision with freshly verified asset bytes. It uses
Python 3.11+ and the standard library, with the existing asset verifier.

This is a read-only prerequisite for local packaging. It does not copy files,
decode audio, measure duration, synthesize, render, record human approval, create
a package, transfer data or publish. Calling an asset "audio" does not prove its
format or listening quality. Transcript and playback contracts remain separate.

## Audio-only record 0.1

All fields are required; unknown fields and duplicate JSON keys fail.

| Field | Contract |
|---|---|
| schema_version | Exactly `audio-candidate-0.1` |
| project_id | Matches the caller-supplied expected project ID |
| content_id | Opaque content identifier |
| audio.asset_id | Project-local asset identifier |
| audio.size_bytes | Integer, not bool, from 0 through 16 GiB inclusive |
| audio.sha256 | Exactly 64 lowercase hexadecimal characters |
| metadata.title | Nonblank text, at most 200 Unicode code points |
| metadata.language | 2–3 lowercase ASCII letters, optionally `-` and 2 uppercase ASCII region letters |
| metadata.credits | Ordered list of 0–16 unique text strings, each nonblank and at most 200 code points |

Identifiers start with a lowercase ASCII letter, contain lowercase letters,
digits and single separating hyphens, and have at most 64 characters. Language
examples are `en`, `ja`, `en-US` and `ja-JP`; this version accepts only that
restricted subset, not every BCP 47 tag. Text rejects Unicode categories Cc,
Cf, Cs, Zl and Zp (including controls, format characters, lone surrogates and
line/paragraph separators). Ordinary spaces and Unicode text are preserved.
Credits are attribution declarations, not verified rights evidence. Empty
credits do not indicate that attribution is unnecessary.

The binary-stream loader accepts UTF-8 JSON without a BOM, at most 64 KiB,
reading in chunks of at most 4 KiB with one extra byte to detect overflow.
Malformed JSON, non-finite values, excessive nesting and invalid fields fail.
Direct dictionary APIs enforce the same field/count/text limits, independently
of input whitespace and serialization layout. Floats are never valid sizes.

## Transcript-bearing record 0.2

`audio-candidate-0.2` requires every field from 0.1 and exactly two additions:

| Field | Contract |
|---|---|
| audio.duration_ms | Independently declared presentation duration, integer (not bool) from 1 through 86,400,000 milliseconds |
| transcript | Object with exactly `fingerprint`: 64 lowercase hexadecimal characters identifying the entire `timed-transcript-0.1` record |

Version 0.2 always selects one required transcript. Neither addition is accepted
in 0.1; there are no optional/null tracks or implicit schema upgrades. Existing
0.1 fingerprints remain unchanged. Duration and the full transcript fingerprint
participate in the 0.2 candidate fingerprint. Changes to cue text, IDs, timing,
language or references therefore require a new candidate selection and matching
decisions. The caller must select the transcript revision and independently
review the declared duration; copying values from arbitrary incoming text does
not establish their accuracy.

Candidate validation checks declarations only. Even for 0.2,
`verify_candidate_asset` and the candidate CLI's `verify` command verify **audio
bytes only**: they do not load a transcript, compare its revision, measure duration
or check speech alignment. The [package API](local-packages.md) performs the
sidecar comparison and binds it to the bytes it actually copies. That API requires
the single transcript's language to equal `metadata.language` exactly; translated
or multiple tracks need a future contract.

## Fingerprints and the selected revision

After validation, all fields are copied into a new record using only primitive
values and a separate credits list. Fingerprinting uses UTF-8 bytes from Python
`json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
allow_nan=False)`, with no BOM or trailing newline, followed by SHA-256. The
schema version is included. This is the versioned contract, not a claim of
compliance with another JSON canonicalization standard.

Object key order and JSON whitespace do not change the fingerprint. Changes to
audio references, project/content IDs or any metadata field do. Credits retain
their order; exact duplicate strings fail. Text whitespace, case and Unicode
normalization are not rewritten: composed and decomposed text are different
revisions. The record contains no timestamps, local paths or implicit defaults.

Verification requires an independently supplied `expected_fingerprint`. A
malformed or different fingerprint fails before asset I/O; the CLI also rejects
it before reading a registry. The expected value pins the caller's selected
revision. It is not authentication, a signature or proof of human approval.
Computing it directly from the current input is useful for identification, but
does not establish that a previously reviewed revision was selected.

## API

- `load_candidate(source, *, project_id)` reads from a caller-owned binary stream
  and returns a validated record. It does not open paths or close the stream.
- `validate_candidate(document, *, project_id)` returns `None` on structural
  success and never reads assets.
- `candidate_fingerprint(document, *, project_id)` returns the lowercase digest
  of the validated record, without verifying asset bytes.
- `verify_candidate_asset(document, *, project_id, expected_fingerprint,
  registry, project_root)` uses one candidate snapshot and calls the existing
  `verify_asset` for a fresh read. It then checks that measured size and digest
  match the candidate's declaration. A valid registry receipt cannot override a
  different candidate declaration. No prior receipt or shared cache is accepted.

Candidate validation, stream loading and failed asset verification raise
`CandidateError` with fixed diagnostics, omitting original I/O errors and input
metadata. Callers provide the expected project ID, trusted absolute root,
registry and selected fingerprint from their own project assignment. They must
not let untrusted metadata select those inputs. IDs are scoped labels rather
than an authorization system; use opaque labels rather than sensitive text.

A successful verification receipt includes the fingerprint, project/content
IDs and measured `audio` reference, with `verified=true` and
`scope=candidate_asset_bytes_only`. It omits metadata text and file paths.
`rights_verified`, `media_qa_passed`, `human_reviewed`, `packaged`,
`external_transfer` and `publication` are always false. Structural validation
returns `scope=candidate_structure_only` and `bytes_verified=false` through the
CLI. Neither result is an approval record.

## Synthetic example

The checked-in candidate uses the same 23 bytes, `b"Neutral asset example.\n"`,
as `examples/asset-registry.json`. They are synthetic text, not a decoded audio
fixture. This Python example creates them only inside a temporary directory:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from narradock_assets import load_registry
from narradock_candidates import load_candidate, candidate_fingerprint, verify_candidate_asset

with Path("examples/candidate-record.json").open("rb") as stream:
    candidate = load_candidate(stream, project_id="sample-project")
selected = candidate_fingerprint(candidate, project_id="sample-project")
registry = load_registry(Path("examples/asset-registry.json"), project_id="sample-project")
with TemporaryDirectory() as directory:
    root = Path(directory).resolve()
    (root / "inputs").mkdir()
    (root / "inputs" / "example.dat").write_bytes(b"Neutral asset example.\n")
    receipt = verify_candidate_asset(candidate, project_id="sample-project",
        expected_fingerprint=selected, registry=registry, project_root=root)
    assert receipt["verified"] and receipt["audio"]["size_bytes"] == 23
    assert not receipt["packaged"] and not receipt["publication"]
```

## CLI

Candidate JSON is read from standard input. The module does not select or open a
candidate filename; the caller controls the input stream. This avoids adding a
second implementation of asset filesystem traversal. The loader applies byte
bounds but no read deadline; a blocked input stream may still wait for its
producer. Supplied candidate content is not constrained by the asset root.

For a POSIX shell, the structural example is:

```text
python -B narradock_candidates.py validate --project-id sample-project < examples/candidate-record.json
```

Expected: exit 0, a fingerprint, `scope=candidate_structure_only` and
`bytes_verified=false`. It creates no assets. The verification form is:

```text
python -B narradock_candidates.py verify --project-id PROJECT --expected-fingerprint FINGERPRINT --registry REGISTRY --project-root ABSOLUTE_ROOT < CANDIDATE_JSON
```

Uppercase words represent the caller's assigned inputs; this is not a supplied
workstation configuration. All four verification arguments are required.
`validate` rejects verification-only arguments. Use `python3` when that is the
verified executable. Success is exit 0; malformed arguments/input, failed
verification or failed output is exit 2 with a fixed diagnostic. A closed output
pipe is handled without a shutdown traceback.

## Limits and next steps

The existing [asset verifier's trust and filesystem limits](asset-registry.md)
apply. Candidate metadata has no path field and cannot broaden asset access.
The receipt observes one asset during this call, not a snapshot that remains
valid after return. It does not guarantee unchanged input on a later open.

Packaging must validate the bytes it actually consumes/copies and safely commit
the output. Trusting this receipt and opening the file again would reintroduce
a change-between-verification-and-use gap. This module intentionally offers no
copy, package or export API and does not claim to solve that later boundary.
The separate [local package API](local-packages.md) now validates caller-supplied
candidate-bound rights, technical QA, human review and local-packaging decisions,
then verifies the same bytes it copies. These records are caller assertions, not
tool-performed reviews. Changed metadata changes the fingerprint, but no approval
database or automatic revocation mechanism is implemented.

`snapshot_candidate(document, project_id=...)` returns an independent validated
dictionary for downstream consumers. Its nested audio, metadata, credits and 0.2 transcript declaration do
not share mutable containers with the input. Taking this snapshot does not verify
bytes or establish any decision; it lets the package API consistently identify,
compare and serialize one revision.

Tests use only neutral temporary bytes. They cover metadata changes, canonical
identity, stale selections, project mixing, fresh verification after file
changes, a stable candidate snapshot, bounded/strict input and private
diagnostics. Run the full existing validation sequence and Linux/Windows CI.
No additional packages, providers, real media or Windows workstation acceptance
are needed or claimed.

## Separate PCM measurements

The [PCM WAV measurement API](audio-measurements.md) measures verified candidate bytes for a limited 16-bit PCM profile and compares actual frame duration with candidate 0.2 declared duration. It does not verify transcript alignment or approve media QA. This contract and its existing behavior remain unchanged; packaging does not automatically consume measurement results.
