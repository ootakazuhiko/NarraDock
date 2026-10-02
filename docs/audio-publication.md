# Audio publication

Status: accepted product direction; adapter implementation and destination selection are pending. Tracking: issue #2.

## Independent route

Audio-only output must not depend on a renderer, presenter image, video channel, or video approval. Existing audio may be registered without synthesis. Imported and synthesized audio follow the same candidate-specific technical QA, rights/credit review, human review, packaging, and publication contracts.

The bootstrap only validates and plans. It does not verify actual audio, create a package, generate a feed, contact a host, or change public visibility.

## Integration intake

A publishing contributor should supply a neutral capability description and independently reviewable code, not operational project records.

| Required decision | Required evidence |
|---|---|
| Inputs | Supported formats, candidate fingerprint, metadata version, transcript/credit needs |
| Destination | Selected adapter type and capabilities; actual accounts/endpoints remain in private configuration |
| Transfer boundary | Whether uploading is private, immediately public, or delayed; no assumed private staging |
| Authentication | Credential reference and permissions, never token values |
| Idempotency | Local release identity, remote identifier, response-loss reconciliation and retry limits |
| Activation | Who authorizes which candidate, destination, visibility, and schedule |
| Recovery | What can be withdrawn or corrected; no unsupported recall guarantees |
| Testability | Offline mocks for success, rejection, timeout, ambiguous success, and changed metadata |

Local export, hosted audio/feed delivery, podcast-host integration, and other destinations are options, not selected providers. Confirm provider capabilities against official documentation before implementing a live adapter.

## Release boundaries

1. Validate the selected candidate and required human decisions.
2. Prepare an immutable, allowlisted local package and its private operational receipt.
3. Obtain explicit transfer authorization. If transfer itself makes content public, publication authorization is required before transfer.
4. Transfer to the selected destination and reconcile its identifiers and processing state.
5. Obtain or verify candidate-bound publication authority, activate only as permitted, then check actual visibility.

Timeout after submission is `unknown`, not automatically failed. Do not submit again until reconciliation establishes a safe retry. Metadata changes invalidate the relevant authorization even if audio bytes are unchanged. Hashes identify bytes, not people or permission.

## Acceptance

A synthetic audio-only release must pass without video tooling. Missing rights evidence, missing authority, changed fingerprints, cross-project access, and unresolved remote outcomes must block the affected operation. An integration PR must document source review, tests, limitations, and the exact scope that is implemented. No existing publication implementation has yet been imported or certified by this document.
