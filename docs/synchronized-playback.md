# Synchronized audio playback and controlled delivery

Tracking: #2; foundation dependency: #1. This is a provider-neutral capability specification, not a destination selection or permission to deploy. Audio-only use does not require video, artwork, synthesis, or a video account. User media, scripts, destinations, credentials, and operational records remain outside public source.

## Implementation boundary

The first increment implements `narradock_transcript.py`, a standalone offline sidecar validator, reference-binding comparison, revision fingerprint, and plain-text WebVTT exporter. `examples/timed-transcript.json` contains newly authored synthetic text, fictional timing, and a placeholder digest. No associated recording exists.

The separate [local package API](local-packages.md) now binds one transcript to an `audio-candidate-0.2`, verifies the audio bytes it copies through the asset registry, and includes canonical transcript JSON and escaped WebVTT in an allowlisted ZIP. The standalone transcript validator still does no media I/O. Its structure/binding results alone are neither approved content nor a release package.

The separate [PCM WAV measurement API](audio-measurements.md) measures frame duration and sample statistics for a limited PCM profile. The [standalone player](standalone-player.md) implements a synthetic browser demo; the [candidate preview API](candidate-preview.md) connects selected candidates to that player after audio, transcript and measured-duration verification. Not implemented: alignment verification, comprehensive media QA, approval recording, authentication, entitlement checks, storage/CDN adapters, DRM, payment, remote transfer, or public activation. The foundation manifest schema and its `package_only` planning restriction remain unchanged.

## Timed-transcript contract

| Field | Contract |
|---|---|
| `schema_version` | Exactly `timed-transcript-0.1`; independent of the foundation manifest version |
| `project_id`, `content_id` | Opaque scoped identifiers, not paths or URLs |
| `language` | Restricted language-tag shape; not full BCP 47 registry validation |
| `audio.asset_id` | Opaque candidate reference; resolved through the registry by the package API, never by this standalone validator |
| `audio.sha256` | Lowercase SHA-256 shape; the offline validator does not read media bytes |
| `audio.duration_ms` | Positive integer presentation duration, at most 24 hours |
| `cues` | 1 to 10,000 chronologically ordered, non-overlapping cues |
| Cue `id` | Unique stable identifier within the sidecar |
| Cue `start_ms`, `end_ms` | Integer milliseconds; `0 <= start_ms < end_ms <= duration_ms` |
| Cue `text` | 1 to 4,000 characters of trimmed single-line plain text |

Identifiers use lowercase letters/digits separated by hyphens, begin with a letter, and have at most 64 characters. Language tags have at most 20 characters. Control, format, surrogate and other Unicode category-C characters, as well as Unicode line/paragraph separators, are rejected in cue text. Markup-looking characters remain literal text. This is a deliberately narrow initial contract, not a general WebVTT parser.

Unknown or missing fields, duplicate JSON keys at every level, non-finite JSON constants, invalid UTF-8, files larger than 2 MiB, empty cues, duplicate identifiers, invalid timings, and overlaps fail closed. The file loader has a byte limit; legacy in-memory validation/fingerprint/WebVTT calls enforce structural/count/text limits. The exporter escapes `&`, `<`, and `>` and preserves integer-millisecond timestamps. It never treats supplied text as HTML or WebVTT markup.

`snapshot_transcript(document)` returns an independent validated copy of root, audio, cue list and cue records. It accepts exact built-in dictionaries/lists/strings/integers rather than custom subclasses, avoiding caller copy hooks. `canonical_transcript_bytes(document)` snapshots and encodes canonical UTF-8 JSON incrementally, rejecting output above 2 MiB before allocating a complete oversized representation. Its SHA-256 matches `fingerprint` for the same revision. These helpers open no paths and leave existing sidecar fingerprints and WebVTT output unchanged. The package API uses them before source/output I/O and caps derived WebVTT at 10 MiB.

Gaps are valid: no cue is active during leading silence, between cues, or after the final cue. The player contract uses half-open intervals `[start_ms, end_ms)`. At an adjacent boundary the following cue is active, never both. Cues are not silently reordered or retimed. Stable cue IDs are for navigation; a text change must still change the revision fingerprint.

`require_binding(document, expected)` compares project ID, content ID, candidate asset ID, declared audio digest, and declared duration. The caller must obtain `expected` from an independently trusted registry. The comparison does not authorize filesystem access or prove that bytes match the declaration; copying the transcript's own fields into `expected` is not verification.

`fingerprint(document)` hashes canonical JSON for the entire validated sidecar, including text, timing, scope, language and audio reference. An `audio-candidate-0.2` includes this fingerprint, independently declared audio duration, byte identity, and delivery metadata. Candidate-bound package decisions therefore cover the selected sidecar revision too. The sidecar fingerprint alone does not cover separate metadata, prove rights, or grant permission. Any relevant change requires matching decisions. Actual duration and alignment remain caller-reviewed declarations, not measurements performed by this API.

## Timing production contract (future implementation)

Sentence/paragraph cues are the initial target. Word-level highlighting is optional future work, not a prerequisite for audio publication. Imported and synthesized audio use the same sidecar format; no speech provider or alignment engine is prescribed.

For segmented synthesis, derive timing from the actual edited segments and the final assembly timeline, including inserted silence, removed silence, crossfades and narration offsets. Accumulate sample counts or rational durations before rounding boundaries to milliseconds, rather than accumulating independently rounded segment durations. Plain duration summation is valid only for truly sequential concatenation with its gaps represented.

Time-preserving gain changes or mixing can retain cue times, but the final media digest still changes. Cuts, tempo changes, time stretching, crossfades, encoder delay, resampling and edited intros require timeline verification and, where appropriate, new alignment. For existing recordings, an optional forced-alignment adapter must report uncertainty and provide a review path; it must not label estimated times as verified ground truth.

Validate the final delivered presentation timeline, not merely intermediate WAV lengths. Audio and video may reuse cues only when their narration timelines match; differing edits need separate audio bindings and cue revisions. Capture alignment evidence privately. No media or alignment logs belong in this repository.

## Browser player contract (synthetic prototype implemented)

The player adapter must provide audio play/pause, seek, elapsed/total time, playback-rate control, cue highlighting, and cue-to-seek navigation. A ten-second skip is an optional UI control, not a schema constraint. The framework must not require a particular frontend framework or player library.

Use the media presentation clock, not a wall-clock timer. Re-evaluate the active cue after seeking, resuming, rate changes and background/foreground transitions; clear highlighting in gaps and at the end. Represent transcript text with `textContent` or an equivalent safe text sink, never unsanitized `innerHTML`.

Auto-follow must be user-controllable and stop fighting deliberate manual scrolling. Do not steal keyboard focus while playback advances. Provide keyboard operation, meaningful control labels, visible focus, readable contrast, reduced-motion behavior and screen-reader access without announcing every timing update. Do not autoplay audible media. Literal [transcript search](standalone-player.md#search-the-current-transcript) is implemented in the shared player; transcript hiding and chapters remain optional future extensions.

Resume position must be scoped to the exact content/media revision; account-level sync is a separate consent and data-retention decision. Changing an episode or signing out must not reuse another user's playback grant or protected transcript. Browser testing must cover desktop and mobile, including Safari's native media path and other selected browser engines. No browser compatibility is claimed by Python tests.

## Protection goal and limitations

The restricted-delivery goal is to deny unauthorized requests and reduce casual saving/link sharing. It is not a promise of undownloadable or unrecordable audio. An authorized endpoint receives playable media, and recording or authorized capture remains a residual risk. Transcript text shown to a reader can also be copied.

`controlsList="nodownload"` is optional UI behavior with uneven browser support, not an access-control mechanism. HLS segmentation alone is not a security boundary, and ordinary stream encryption with a key accessible to the authorized client is not equivalent to DRM. Signed progressive audio can also provide access control; HLS must be justified by delivery/player requirements, not described as copy prevention. DRM is a separately reviewed optional provider capability, not part of this increment and not a guarantee against recording.

A generic product may support intentionally public/downloadable releases as well as restricted web access. The policy must be explicitly selected per release/destination. A publicly retrievable podcast enclosure is not compatible with a restricted no-direct-file-download requirement. Do not silently select a podcast destination for a restricted web release.

## Restricted-delivery adapter contract (future implementation)

1. Keep origin media private and deny direct-origin bypass. Separate source masters from approved delivery renditions; never expose a master merely because a preview is approved.
2. Authenticate the viewer and check entitlement for the requested project/content/revision before granting playback. A real restricted-content pilot needs authorization from its first release; an unauthenticated prototype may use only explicitly public synthetic fixtures.
3. Authorize every protected resource: master/media playlists, initialization fragments, segments, encryption-key endpoints when applicable, transcripts, and restricted metadata. A signed master-playlist URL does not automatically sign child URLs. Apply checks even on cache hits, and test direct object and range requests.
4. Use scoped, expiring playback grants through a selected signed-cookie, signed-URL, or token adapter. Do not hard-code a global lifetime. Renew before expiry through a fresh entitlement check, and define behavior after logout, expiry and revocation. Bearer grants may be replayable until they expire; short lifetime is not immediate revocation.
5. Define cache, CORS, cookie and CSRF policies for the chosen browser path. CORS and hidden URLs are not authorization. Do not expose credentials in source, manifests, analytics, error text, referrers or public logs. Native and JavaScript playback paths must have equivalent protection; never fall back silently to a public media URL.
6. Define rate/concurrency limits and privacy-preserving operational evidence. Do not introduce tracking, user watermarking or identity-bearing media by default.

Credential indirection, capabilities, immutable package identity, transfer authority, activation authority, reconciliation and rollback follow [audio-publication.md](audio-publication.md). Response loss produces `unknown` and blocks blind resubmission. A provider whose transfer immediately publishes requires publication authority before transfer. Withdrawal cannot recall previously received copies.

No production endpoint, account, credential, CDN, payment service or hosting destination is selected by this document. Official provider documentation below illustrates requirements; it does not select that provider.

## Incremental delivery and acceptance

| Increment | Required evidence | Status |
|---|---|---|
| Timed-transcript contract | Synthetic validation, binding mismatch, deterministic fingerprint, safe VTT and CLI tests | Implemented in this change |
| Standalone player | Synthetic-only page; highlighting, gaps, seek, rate, pause/resume, manual-scroll and accessibility tests | Implemented with generated tones, Python/Node checks and explicit Chromium acceptance; other browsers/devices pending |
| Candidate preview | Selected candidate, bound transcript and verified PCM bytes in private HTML | [Offline API implemented](candidate-preview.md); measured duration required, alignment and approval recording remain separate |
| Playback notes | Fixed time/cue notes, private JSON export and selected-revision validation | [Implemented](review-notes.md); notes are not authenticated review completion or package decisions |
| Candidate-aware packaging | Verified audio bytes, sidecar and metadata revision binding, allowlisted package, private receipt; separately reviewed timeline QA | Offline package implemented; measured timeline QA remains pending |
| Restricted adapter | Explicit destination and entitlement model; denied unauthenticated/cross-scope/cache/origin requests; expiry/renewal tests | Planned |
| Reviewed pilot | Explicit environment and separate transfer/activation authority, selected-browser checks, reconciliation and rollback evidence | Not authorized |

Follow-up tests must include rejected/expired/revoked grants, copied grants within their documented validity, direct segment/init/key/transcript access, cross-project and cross-user access, cache leakage, changed metadata and changed audio, duplicate prevention after response loss, and a long listening session spanning renewal. Python reference-comparison tests are not runtime-isolation or CDN-security tests.

## Offline validation and recovery

Executor: an assigned developer or CI job in an independently assigned checkout/worktree, using Python 3.11+ and Git. Follow [development.md](development.md) for path, branch/HEAD, permitted-file, process and recovery prerequisites. No Windows worktree or production environment is assigned by this generic document. Stop when that assignment is missing; do not reuse another project's checkout.

The standalone CLI accepts `validate` or `vtt` followed by one explicitly supplied transcript filename. `validate` writes only a structural summary and fingerprint; media/binding verification and transfer/publication flags remain false. `vtt` writes UTF-8 WebVTT to stdout, not to a file or network destination. The caller owns any explicit redirection. Do not send a real transcript's stdout to public CI logs. The synthetic test suite is discovered by the existing CI workflow without new permissions or dependencies.

Success is exit 0. Invalid input or output failure is exit 2 with sanitized diagnostics; stop the affected operation and retain evidence privately. No asset lookup, mutation, provider call or publication occurs. Do not relax validation to continue. Read-only validation needs no restoration; any explicitly redirected output must be handled in the assigned private output area. Rejecting the unmerged implementation means abandoning its dedicated Draft PR; after merge, use a reviewed correction/revert PR, not a reset of shared history.

## Primary references

- [W3C WebVTT](https://www.w3.org/TR/webvtt1/) specifies timed cue syntax. NarraDock deliberately rejects overlaps even though WebVTT can represent them.
- [MDN controlsList](https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement/controlsList) describes native-control selection and limited availability.
- [MDN HTMLMediaElement](https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement) documents the media clock and seeking interface.
- [CloudFront private content](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/PrivateContent.html) documents signed access and restricting origin bypass.
- [CloudFront signed URLs or cookies](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-choosing-signed-urls-cookies.html) discusses access to multiple HLS files.
- [CloudFront signed cookies](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-signed-cookies.html) documents expiration and renewal considerations.

## Separate PCM measurements

The [PCM WAV measurement API](audio-measurements.md) measures verified candidate bytes for a limited 16-bit PCM profile and compares actual frame duration with candidate 0.2 declared duration. It does not verify transcript alignment or approve media QA. This contract and its existing behavior remain unchanged; packaging does not automatically consume measurement results.
