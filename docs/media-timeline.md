# Candidate-bound chapter timeline

`narradock_timeline.py` connects a private chapter sidecar to a selected version
0.2 audio candidate, its timed transcript and freshly verified PCM WAV bytes.
This first `media-timeline-0.1` profile contains chapters only. It does not infer
chapter boundaries, edit media, add BGM/scene/presenter tracks, or change the
existing candidate, transcript, player or package formats.

## Input and selection

The root has exactly these fields:

| Field | Meaning |
|---|---|
| `schema_version` | `media-timeline-0.1` |
| `project_id`, `content_id`, `language` | Scope matching the selected candidate and transcript |
| `candidate_fingerprint` | Complete candidate revision, including audio bytes and metadata |
| `transcript_fingerprint` | Complete canonical timed-transcript revision |
| `clock` | Exactly `sample_rate_hz` and `frame_count` |
| `chapters` | Ordered array of chapter records |

Each chapter has exactly `id`, `title`, `start_frame`, `end_frame`. Intervals are
half-open `[start_frame, end_frame)`. Starts and ends are integer **PCM frame**
boundaries; one frame includes all channels at one instant. Stereo does not
double the clock rate. Chapters must have unique IDs, positive lengths, and
non-overlapping intervals in supplied order, within `[0, frame_count]`. Gaps and
adjacency are allowed; complete coverage and correspondence with cue boundaries
are not required. The end boundary may equal `frame_count`, but no chapter can
start there. Entries are never sorted, truncated, merged or inferred from text.

Titles are literal, single-line strings of 1–200 Unicode code points, with no
leading/trailing whitespace, Unicode category `C` characters, U+2028 or U+2029.
Interior spaces, markup-looking text and Unicode normalization distinctions are
preserved. A future renderer must use an appropriate plain-text sink; this API
does not render titles as HTML. Titles and chapter locations are private project
data, not public-source fixtures.

The [neutral example](../examples/media-timeline.json) has placeholder revision
hashes. Loading it checks structure only; it does not identify existing media.

## Python API

```python
from narradock_timeline import load_timeline, timeline_fingerprint, verify_timeline

timeline = load_timeline(private_json_bytes, project_id=assigned_project_id)
# The caller reviews/selects this timeline revision and independently selects
# the candidate revision. Copying the timeline's candidate field is not selection.
timeline_revision = timeline_fingerprint(timeline, project_id=assigned_project_id)
receipt = verify_timeline(
    timeline,
    project_id=assigned_project_id,
    expected_fingerprint=timeline_revision,
    candidate=selected_candidate,
    expected_candidate_fingerprint=selected_candidate_revision,
    transcript=selected_transcript,
    registry=project_registry,
    project_root=trusted_project_root,
)
```

- `load_timeline(data: bytes, *, project_id)` parses bounded strict UTF-8 JSON
  without a BOM, rejecting duplicate keys at every level, non-finite constants,
  unknown fields and invalid values. It opens no path.
- `snapshot_timeline(document, *, project_id)` returns an independent validated
  copy of exact built-in primitives. It performs no asset I/O.
- `timeline_fingerprint(document, *, project_id)` returns SHA-256 of the entire
  validated canonical document: UTF-8, `ensure_ascii=False`, sorted keys, compact
  separators and no trailing newline. JSON key order, indentation and equivalent
  escapes do not change identity. Titles, intervals, order, scope, clock and both
  bound revisions do. This is not a raw-file hash, signature or approval.
- `verify_timeline(...)` first snapshots and checks both independent selections,
  candidate version, scope, language and transcript revision/reference binding.
  These gates precede asset I/O. It then calls the existing
  `measure_candidate_wav` for one fresh guarded read. Candidate bytes must match
  the registry, measured rate/frame count must exactly match the declared clock,
  and measured duration must round to the candidate/transcript duration using
  the existing nearest-ms-half-up rule. No cached or caller-supplied measurement
  receipt can substitute for that read.

All failures raise `TimelineError("Media timeline could not be validated")`,
without supplied text, paths or lower-level I/O details. No success receipt is
returned after a failed final read guard, parse, digest or clock check. The API
writes no files, invokes no engine, and grants no authority to transfer or publish.

## Exact time and millisecond projections

The canonical timeline always retains the exact frame positions. Time at boundary
`f` is the rational number `f / sample_rate_hz` seconds. The verification receipt
adds an integer millisecond projection for each absolute boundary:

```text
ms = (2 * f * 1000 + sample_rate_hz) // (2 * sample_rate_hz)
```

No floating point or sum of rounded interval durations is used. At 44,100 Hz,
210 adjacent 21-frame chapters finish at frame 4,410, or 100 ms. Rounding each
chapter length before adding would incorrectly produce 0 ms. A very short chapter
can have equal projected `start_ms` and `end_ms`; its original positive frame
interval remains authoritative. This projection is not a new timed-transcript
cue and does not relax that contract's positive-duration/non-overlap rules.

The existing transcript's integer-ms timing is unchanged. Its declared
`audio.duration_ms` may differ from the exact PCM endpoint by up to half a
millisecond under the existing duration rounding policy; the last cue can end
earlier. Clock/reference verification does not establish that
words or chapter meanings align with the audio. Editing, adding an intro/outro,
speed changes, resampling, crossfades and encoder delays require a new candidate
and explicit timeline/transcript work; this API provides no automatic remapping.
Even a gain-only byte change invalidates the old candidate binding.

## Receipt and limits

The private `media-timeline-verification-0.1` receipt contains the timeline,
candidate and transcript fingerprints; project/content/language; the exact clock;
chapters with both frame and ms boundaries; the rounding rule; and the existing
[PCM measurement receipt](audio-measurements.md), including the measured audio
hash and size. Its scope is `candidate_pcm_chapter_timeline_only`.
`bytes_verified` and `clock_verified` are true only after all checks succeed.
Rights, media QA, human review, transcript alignment, chapter alignment,
packaging, transfer and publication flags remain false. The full candidate hash
also binds delivery metadata: changing that metadata requires a new timeline
binding even when audio bytes are unchanged.

| Limit | Value |
|---|---|
| Raw JSON bytes and canonical input bytes | 256 KiB each |
| Canonical receipt bytes | 512 KiB |
| Chapters | 1–1,000 |
| IDs | 1–64 characters, lowercase ASCII hyphen-separated identifiers |
| Language | Up to 20 characters, existing transcript tag shape; must also match candidate language |
| Sample rate | Integer 8,000–192,000 Hz |
| Frame count | 1 through `sample_rate_hz * 86400` (24 hours) |

Booleans, numeric strings, floats, custom primitive subclasses, extra fields and
unknown tracks are rejected in timeline inputs. The canonical-size limits apply
to compact UTF-8 encodings; other serializers may produce larger files. Actual
verification also inherits the existing PCM measurement profile and 1 GiB WAV
limit; accepting a structural 24-hour timeline does not imply a WAV of that size
can be verified. No full WAV is retained by this API.

The caller owns the trusted project root, registry and independent selections.
The asset verifier's link/reparse restrictions, mutation checks and documented
race limitations still apply. Snapshots prevent later caller mutation from
changing a selected result, but are not an atomic transaction across concurrent
writers. Receipts describe one observation, not a guarantee of future file state,
authenticated authorship or permission. Chapter UI, package inclusion, BGM,
scene/presenter tracks, alignment and real-media/device acceptance remain future
work. Tests use temporary generated PCM and neutral text only.
