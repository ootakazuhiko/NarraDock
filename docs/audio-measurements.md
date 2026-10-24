# Candidate-bound PCM WAV measurements

`narradock_audio.py` provides offline Python APIs, `measure_candidate_wav` and `read_candidate_wav`. Both measure one selected audio candidate through the same guarded reads used to verify the asset's SHA-256 and size. The latter also returns the exact verified bytes with a smaller input cap. They create no files and require no third-party package, audio device, engine or provider. There is no measurement CLI.

## Call and verification boundary

```python
from narradock_audio import measure_candidate_wav

result = measure_candidate_wav(
    candidate,
    project_id=assigned_project_id,
    expected_fingerprint=selected_candidate_fingerprint,
    registry=asset_registry,
    project_root=trusted_project_root,
)
```

The caller supplies the existing [candidate](candidate-records.md) and [asset registry](asset-registry.md) documents and an explicitly assigned trusted absolute project root. Candidate versions 0.1 and 0.2 are supported unchanged. The function snapshots the candidate, checks its complete fingerprint and size limit before asset I/O, then streams `copy_verified_asset` into an internal measurement sink. It never verifies a path and reopens it for parsing. Tentative measurements are discarded if the source verifier fails, including its final identity/change guards. Only after registry verification, comparison with the selected candidate's size/hash and complete WAV parsing does a result become available.

The existing verifier's trusted-root, ancestor/mount and race limitations apply; this is not an OS sandbox. The observation describes bytes read during that call and is not a guarantee about later file contents. Invalid, unsupported or unverifiable input raises `AudioMeasurementError` with a fixed message, without source paths or metadata. The caller handles that failure; no partial result or audio copy is returned.

`read_candidate_wav` takes the same arguments and returns `(wav_bytes, result)` after the same final checks. Its input ceiling is 32 MiB, checked before asset I/O; `measure_candidate_wav` retains its streaming 1 GiB ceiling. The receipt and duration-mismatch behavior are identical. Captured bytes include every original header, pad byte and permitted opaque metadata chunk. There is no second source read, file output or metadata sanitization. This bounded capture supports the separate [candidate preview API](candidate-preview.md).

## Deliberately limited WAV profile

| Property | Accepted value |
|---|---|
| Container | Little-endian `RIFF` / `WAVE`, exact declared and observed length |
| Format | Exactly one 16-byte `fmt ` chunk, PCM format code 1, signed 16-bit little-endian |
| Channels and rate | Mono or stereo; integer sample rate 8,000 through 192,000 Hz |
| Layout | Block alignment equals channels times 2; byte rate equals sample rate times block alignment |
| Samples | Exactly one nonempty, frame-aligned `data` chunk after `fmt ` |
| Additional chunks | `JUNK` and `LIST` whose first four payload bytes are `INFO`, before or after audio |
| Limits | File at most 1 GiB; at most 128 chunks including `fmt ` and `data`; aggregate additional-chunk payload at most 1 MiB |

Every chunk must fit inside RIFF, including its mandatory odd-length padding byte. The pad byte's value is ignored. `LIST/INFO` payload after the subtype is parsed opaquely: nested metadata structure and semantics are not validated or included in measurement receipts. `read_candidate_wav` preserves the original metadata in its returned bytes. Metadata payload limits include the `INFO` subtype and exclude chunk headers/padding. Duplicate format/data chunks, unknown chunks, partial frames/headers/padding, and trailing bytes are rejected. RF64, RIFX, extensible WAV, extended format chunks, floating-point PCM, compressed audio and other sample widths are unsupported. A valid WAV outside this profile is still rejected; callers must not interpret that as proof that the file is corrupt.

Measurement-only memory does not scale with advertised chunk sizes. Parsing retains only small headers, at most three incomplete frame bytes, the verifier's bounded read block and fixed channel counters. `read_candidate_wav` additionally retains the complete source and creates immutable result bytes; its 32 MiB file limit is not a process-memory limit. Length and metadata/count limits also bound work, but neither file ceiling is a CPU deadline or real-time guarantee.

## Result contract: `pcm-wav-measurements-0.1`

The result has `measured: true`, `bytes_verified: true` and `scope: candidate_pcm_wav_measurements_only`. It carries the full candidate fingerprint, project/content IDs, and an `audio` record containing the asset ID, verified SHA-256 and byte size. It includes no source path, title, credits, transcript text, metadata payload or sample waveform.

`pcm` contains:

- `format: signed-16-le`, `channels`, `sample_rate_hz` and `frame_count`. One stereo frame contains two samples.
- `sample_peak_abs`: each channel's largest absolute integer sample value, in channel order; the reference magnitude is 32768. Positive full scale is 32767 and negative full scale has magnitude 32768.
- `full_scale_sample_count`: each channel's count of samples equal to -32768 or 32767. Endpoint samples are observations, not proof of clipping.
- `zero_frame_count`: frames in which every channel is exactly zero. This is not a measurement of perceived silence or a silence-interval detector.

`duration` contains the exact rational milliseconds as `milliseconds_numerator = frame_count * 1000` and `milliseconds_denominator = sample_rate_hz` (not necessarily reduced). `rounded_ms` uses nearest integer milliseconds with ties rounded up, identified by `rounding: nearest_ms_half_up`. A nonempty file shorter than half a millisecond can round to zero.

For candidate 0.2, `declared_ms` is its declared audio duration and `matches_declared` compares it with `rounded_ms`, with no extra tolerance. A mismatch returns the successful byte-bound observation with `findings: ["duration_mismatch"]`; it does not throw or modify the candidate. For 0.1, both fields are null because that schema has no declared duration. Otherwise `findings` is empty. An empty findings list is not a QA pass.

`rights_verified`, `media_qa_passed`, `human_reviewed`, `transcript_alignment_verified`, `packaged`, `external_transfer` and `publication` are always false. Matching duration does not verify cue alignment, spoken content, intelligibility, loudness, true peak, codec quality or permission. Transcript-bearing candidates are fingerprint-bound, but this API does not load or validate the transcript itself.

## Relationship to review and packaging

The observation can inform a caller's technical review. It is not an authenticated approval or a new package decision schema. [Local packaging](local-packages.md) still requires its existing candidate-bound caller decisions and independently verifies the bytes it copies; it does not consume or automatically trust these measurements. Candidate, transcript, package and legacy byte-verification formats remain unchanged.

Tests generate neutral PCM bytes in temporary directories. They cover a standard-library WAV writer, mono/stereo counts, rational duration and half-millisecond rounding, every read boundary in a small metadata-bearing file, exact captured bytes across multiple read blocks, malformed extents/formats, resource limits, stale selections, changed sources and final verifier failure. No real media or binary fixture is committed. The separate candidate preview supplies synchronized playback; loudness analysis, additional codecs and live-media acceptance remain future work.
