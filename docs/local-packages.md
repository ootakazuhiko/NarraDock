# Local audio packages 0.1

`narradock_packages.create_audio_package` creates one offline ZIP from an
[audio candidate](candidate-records.md), freshly consumed asset bytes, and
explicit candidate-bound decisions. Python 3.11+ and the standard library are
sufficient. This is a Python API; there is no package CLI or decision JSON loader.
It does not decode media, measure audio quality, authenticate reviewers, transfer
content, or publish it. Audio-only packaging needs no video or synthesis tool.

## Required decisions and trust

The caller independently supplies the project assignment, selected candidate
fingerprint, registry, absolute project root, and private output directory. A
fingerprint identifies content; it does not grant authority. The caller must
authenticate the decision makers, inspect evidence, check current validity and
ensure that the approval covers the candidate's audio, title, language and credits.
This API cannot inspect an evidence store, establish rights, detect revoked
decisions, or stop another process from using stale assertions.

The decision input is an exact built-in dictionary with these required fields.
Unknown/missing fields, wrong primitive types and unapproved statuses fail.
IDs start with a lowercase letter and contain lowercase letters, digits and
single separating hyphens, up to 64 characters. References are opaque labels,
never paths, account details, evidence text or secrets.

| Field | Required value |
|---|---|
| schema_version | `audio-package-decisions-0.1` |
| project_id | The caller's expected project |
| candidate_fingerprint | The exact selected candidate fingerprint |
| decision_id | Opaque decision record ID |
| rights | `status: approved`, `evidence_id: ID`; covers rights and credits |
| technical_qa | `status: approved`, `evidence_id: ID`; caller's technical QA evidence |
| human_review | `status: approved`, `evidence_id: ID`, `reviewer_id: ID` |
| local_packaging | `status: approved`, `authority_id: ID`; explicit authority for local packaging |

Each nested record has exactly the keys in the table. `pending`, `rejected`, empty
references and implicit truthy values do not qualify. Candidate and decisions
are copied into independent validated snapshots. Candidate validation and
candidate-bound decision failures precede all source/output filesystem I/O. Changing any candidate field
requires matching decisions and a newly selected fingerprint. These checks record
the caller's assertions, not tool-performed rights verification or media QA.

Dictionary validation has field and string limits, not an input JSON byte limit.
An application importing decision JSON must use its own bounded, duplicate-key
rejecting parser and trusted decision workflow. Merely loading an arbitrary
dictionary from a file does not authenticate its author. Synthetic test approvals
are not operational records and must never be reused for real content.

## API and output

```python
from narradock_packages import create_audio_package

# All inputs below come from the application's private, independently checked
# project assignment and decision workflow, not from this repository's examples.
# receipt = create_audio_package(
#     candidate, project_id=expected_project_id,
#     expected_fingerprint=selected_candidate_fingerprint,
#     decisions=current_authenticated_decisions, registry=project_registry,
#     project_root=absolute_project_root,
#     output_directory=absolute_private_output_directory,
# )
```

The existing output directory must be private, local and under trusted control,
including its ancestors and mount topology. It must not have concurrent writers.
Parents are not created. The resolved output directory must be outside the source
project root; aliases back into that root fail. Absolute paths without `..` are
required; Windows paths must resolve to drive-letter paths, not UNC/device paths.
Mapped drives and network mounts are not comprehensively detected: local private
storage is a caller precondition. This is not a hostile-output-tree sandbox.

The final filename is `<candidate fingerprint>.zip`. Existing files, directories
and symlinks at that name are never overwritten, including a previous successful
package with different decision records. Use another explicitly assigned output
directory for an intentional repeat; there is no automatic reuse or overwrite.
The archive contains exactly these fixed names, in this order:

| Member | Content |
|---|---|
| audio.bin | Copied bytes matching both the registry and candidate's size/SHA-256 |
| candidate.json | The complete canonical candidate, including delivery metadata |
| manifest.json | `audio-package-0.1`, project/content IDs, candidate fingerprint, and size/SHA-256 of the other two members |

No source paths, registry, decision evidence, actor references, private receipt,
transcript, or unrelated directory contents enter the archive. `.bin` deliberately
does not assert a verified codec. Candidate metadata is intended package content;
the caller must review it for disclosure. JSON is UTF-8, sorted keys, compact
separators, unchanged Unicode and no BOM/newline. ZIP uses stored bytes, fixed
1980-01-01 timestamps, explicit Unix file attributes and ZIP64 for the audio member.
It is deterministic for the same candidate and source bytes in supported Python
runtimes; synthetic tests verify repeated builds. Future format changes may change
the ZIP digest without changing the candidate fingerprint.

## Verification and finalization

The packager calls `copy_verified_asset`, which shares the asset verifier's
protected traversal and final stability checks. Hashing and copying consume the
same bounded reads while its guarded file handle remains open. There is no later
reopen based on a verification receipt. Source reads remain at most 64 KiB, and
the declared size remains capped at 16 GiB; memory use does not scale with audio
size. Disk space must accommodate the uncompressed asset and small ZIP/JSON overhead.

Provisional bytes go only into an exclusively created private staging file in the
output directory. POSIX staging mode is 0600; Windows inherits the directory ACL.
After source verification, candidate comparison, manifest writing and ZIP close,
the file is flushed and synced. Its full bytes are hashed on the same open handle
with a completed-size-plus-one read bound. This hashes the archive; it is not a
second media decode or an independent semantic validation of every ZIP member.

After file close succeeds, `os.link` creates the final name exclusively, then the
staging name is removed. A local filesystem with hard-link support is required;
unsupported filesystems fail without a weaker rename/overwrite fallback. A complete
file becomes visible at the final name in one link operation. The final file has
one link after normal completion. Content identity and this API's no-overwrite rule
do not make the file immutable to its owner, other privileged processes or later
edits. No directory fsync/crash-durability guarantee is made.

Only then does the API return a private receipt: `packaged=true`,
`scope=local_audio_package_only`, project/content IDs, candidate fingerprint,
`decisions_bound=true`, decision fingerprint, and package size/SHA-256. Decision
fingerprints hash all decision fields using the same JSON encoding described above.
The package digest hashes the entire completed ZIP. These three fingerprints serve
different purposes. `rights_verified`, `media_qa_passed`, `external_transfer` and
`publication` stay false. Keep the receipt and decision record in private storage;
neither is publication or transfer authority.

Failures raise `PackageError` with fixed diagnostics. Normal failures clean up
only files created by that call; existing destinations are preserved. Cleanup
attempts both owned paths even if one removal fails. Process termination, power
loss or cleanup failures can leave staging files or a complete final ZIP without
a successful receipt. A failed return is not proof that no output exists. Inspect
and reconcile leftovers privately; do not treat their presence as approval or
blindly retry, publish, overwrite or delete an existing package.

## Scope and validation

The asset verifier's [filesystem trust limits](asset-registry.md) still apply.
There are no hard I/O deadlines, OS-enforced immutability, approval database,
revocation service, signature verification, transcript packaging, UI, media
processing, upload, RSS, playback or publication adapter in this increment.

Run the full [development validation](development.md). Tests use temporary neutral
bytes and fictitious decisions, cover source/decision changes, snapshot mutation,
short writes, fixed archive contents, metadata preservation, deterministic builds,
collisions, failed finalization and cleanup. Linux and Windows CI complement each
other; opposite-platform filesystem tests have explicit skips. Synthetic CI is
not real-media QA, rights review or workstation acceptance.
