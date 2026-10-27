# Candidate-bound local audio preview

`narradock_preview.build_candidate_preview` returns one self-contained HTML page
and a receipt in memory. It connects a selected version 0.2 candidate, its timed
transcript and verified PCM WAV to the [synchronized player](standalone-player.md).
It is an offline Python API: no file import UI, CLI, server, browser launch,
output writing, approval recording, packaging or publication is performed.
The returned page now has [playback notes](review-notes.md): a listener can
annotate fixed positions and explicitly request a private JSON download.
Previously saved notes can be supplied when generating another preview of the
same selected candidate and transcript.

## Call and selection

```python
from narradock_preview import build_candidate_preview

html_bytes, receipt = build_candidate_preview(
    candidate,
    project_id=assigned_project_id,
    expected_fingerprint=selected_candidate_fingerprint,
    transcript=timed_transcript,
    registry=asset_registry,
    project_root=trusted_project_root,
    review_notes=saved_note_json_bytes,  # Optional; omit or pass None to start empty.
)
```

The trusted caller provides the same explicitly assigned absolute project root
as the [asset verifier](asset-registry.md). The API snapshots the candidate and
sidecar, requires the complete selected candidate fingerprint, and compares the
sidecar's project/content IDs, audio asset ID, SHA-256 and declared duration with
the candidate. Language and the complete canonical transcript fingerprint must
also match. Version 0.1 candidates have no bound transcript and are rejected.
These checks and the input limits run before asset I/O.

Optional `review_notes` bytes pass the existing strict
[note loader](review-notes.md#python-validation), including scope, full candidate
and transcript revisions, cue references, text and size limits, before audio I/O.
The generated page begins with that editable snapshot. Stale notes are rejected;
there is no automatic migration, browser file import or automatic persistence.
Saved notes never bypass the following source verification.

`read_candidate_wav` captures and measures the same stream delivered by the
guarded asset verifier. Only after its final source-change checks, registry and
candidate size/hash comparisons and complete PCM parsing succeed may those
bytes reach the renderer. There is no second source read. Existing trusted-root,
ancestor/mount and race limitations apply; this is not an OS sandbox or a
guarantee about subsequent source contents.

Measured duration must equal the candidate's declared duration after
`nearest_ms_half_up` rounding. This uses the existing measurement contract,
including the half-millisecond case; it is not sample-exact cue alignment.
A mismatch rejects the preview, while the separate measurement/read APIs still
return that observation with `duration_mismatch` in their findings.

## Bounds and failures

| Input/output | Limit |
|---|---|
| WAV | 32 MiB, with the existing limited signed 16-bit PCM profile |
| Transcript | At most 1,000 cues and 2 MiB canonical UTF-8 JSON |
| Escaped transcript payload | 8 MiB UTF-8 after HTML raw-text escaping |
| Saved note JSON | 512 KiB UTF-8, at most 100 notes of 1,000 Unicode code points each |
| Escaped note payload | 2 MiB UTF-8 after HTML raw-text escaping |
| Complete HTML | 64 MiB UTF-8, including base64 audio and inline assets |

The exact supported WAV profile and its chunk limits are in
[audio-measurements.md](audio-measurements.md). Limits include equality. Input
limits and a lower bound on encoded output are checked before source reading;
the final HTML size is checked before joining the output. These are payload
limits, not a process-memory or CPU guarantee: snapshots, JSON, captured bytes,
base64 and output can coexist in memory. This API is for bounded local previews,
not streaming or long-form audio.

Invalid, unsupported, stale, mismatched or unverifiable input raises
`PreviewError` with `Candidate audio preview could not be created`, without
caller text or filesystem paths. No partial page/receipt is returned. A trusted
caller handles errors and owns any explicit saving of the returned UTF-8 bytes.

## Page, receipt and privacy

The page shows the selected title, credits and candidate identity along with
native audio controls, cue navigation, rate control and optional auto-follow.
It does not autoplay. The content language is set independently of the Japanese
interface. Metadata is HTML-escaped, transcript and note JSON are escaped for raw-text
context, and cue text is inserted with `textContent`. The same strict inline
script/style hashes and embedded-audio content policy as the demo apply. The
page makes no network requests and uses no storage, external fonts or scripts.

**The HTML is private content, not a sanitized distribution artifact.** It
contains the exact original WAV, including permitted opaque `JUNK`/`LIST/INFO`
metadata, the transcript, selected display metadata and any initial notes. Those fields can
themselves contain private information. Registry paths are not rendered, but
neither content inspection nor metadata removal is performed. Copying the HTML
copies its embedded media and text; the content policy is not access control.
Keep real previews and receipts in the assigned private workspace, outside this
repository, public CI and PR attachments.

The `candidate-audio-preview-0.1` receipt contains `preview_created: true`,
`scope: candidate_local_preview_only`, project/content IDs, full candidate and
transcript fingerprints, the existing byte-verified PCM `measurements`, and
`html.size_bytes`/`html.sha256` for these exact output bytes. It contains no
source paths, transcript or note text, titles, credits or waveform. The HTML
identity includes the initial note snapshot; later browser edits do not update
the generated HTML or receipt. It is not signed or
an authenticated decision record. Its `rights_verified`, `media_qa_passed`,
`human_reviewed`, `transcript_alignment_verified`, `packaged`,
`external_transfer` and `publication` fields are all false.

No approved package or approval assertions are required to inspect a candidate.
Listening and transcript alignment still require human evaluation. The page's
optional notes do not record completion or approval and do not feed decisions
into packaging. The existing
candidate, transcript, package and demo APIs retain their contracts.

## Validation

Python tests use temporary synthetic PCM and cover revision/scope binding,
same-read capture, final verifier failure, duration mismatch/rounding, bounds,
literal rendering, source metadata preservation and receipt semantics. Saved-note
tests also cover rejection before audio I/O, raw-text escaping, bounds, snapshot
isolation and fresh source verification. The
existing Node controller tests also apply. `tests/check_preview_browser.py` is
an explicit acceptance tool for an already installed Playwright/Chromium; it
constructs a candidate from generated tones, then serves only its in-memory
page on loopback. Optional screenshots and generated fixtures go only to the
caller-selected private evidence directory. It does not serve filesystem paths.
Browser acceptance is separate from CI. Safari, mobile devices, screen readers,
long listening sessions, real-media acceptance and actual background throttling
are not established by these checks.
