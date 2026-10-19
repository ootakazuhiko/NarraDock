# NarraDock

**Scripts to audio and video, with review and publication kept under control.**

NarraDock is a public personal product for reusable media-production workflows. Audio-only publication is a first-class path, not a side effect of video production.

[日本語](README.ja.md) · [Architecture](docs/architecture.md) · [Audio publication](docs/audio-publication.md) · [Roadmap](docs/roadmap.md)

## Status: pre-alpha

Implemented in the bootstrap: strict manifest validation, deterministic **symbolic planning**, neutral examples, unit tests, and a public-source inventory check. Python 3.11+ and Git are sufficient for these checks; no third-party Python packages are required.

Also implemented: [project-local asset registries and byte verification](docs/asset-registry.md). The `narradock_assets.py` CLI separates registry structure validation (`validate`) from read-only asset resolution and streamed SHA-256/size verification (`verify`) beneath an explicitly supplied trusted project root. Verified bytes do not establish rights, media QA, or publication approval.

The [timed-transcript contract](docs/synchronized-playback.md) is also implemented in `narradock_transcript.py`: structural validation, caller-supplied reference comparison, a full-transcript revision fingerprint, and escaped plain-text WebVTT export. It does not verify media bytes or connect to the asset registry; synchronized browser playback remains unimplemented. The digest and timing in `examples/timed-transcript.json` are placeholders.

**Not implemented:** synthesis, media rendering, media QA, review UI, upload, RSS generation, or publication. Plan entries name future operations; the `narradock.py` CLI never performs them and never records approval.

Hashes in `examples/audio-only.json` and `examples/video-enabled.json` remain placeholders, not verified media fingerprints. `examples/asset-registry.json` declares the hash and size of reproducible synthetic bytes described in the [asset registry example](docs/asset-registry.md#cli-and-a-reproducible-synthetic-example); actual verification requires creating those bytes and running the verifier. Structural validation alone does not verify them.

## Product boundaries

Shared code and neutral examples belong here. Project scripts, media, brands, voice selections, operational credentials, reviews, caches, logs, and publication records belong in isolated user workspaces. This repository is not a content-hosting location.

Production, technical QA, human review, candidate selection, external transfer, and publication are separate decisions. Public source visibility grants none of those operational permissions.

## Development entry

Read [development prerequisites and validation](docs/development.md) before running the bootstrap CLI. The audio-only and video-enabled manifest examples demonstrate existing-audio reuse and a script-to-video proposal without contacting an audio engine or publisher.

[Audio candidate records](docs/candidate-records.md) identify one asset and its delivery metadata as a selected revision, and can compare that revision with freshly verified asset bytes. The candidate CLI reads JSON from standard input. This implemented contract does not create a package or establish rights, media QA, human approval, transfer, or publication permission.

The initial version is `0.1.0a1`; no installable package or release has been published. Runtime data must not be committed even when ignored files can be force-added.

[Local audio packaging](docs/local-packages.md) is available through the `narradock_packages.py` Python API. It requires candidate-bound caller decisions, verifies the bytes it copies, and creates a fixed-member ZIP without overwriting existing output. Version 0.2 candidates bind one timed transcript and its declared audio duration; packages include canonical transcript JSON and escaped WebVTT. Existing audio-only 0.1 output is preserved. Decision records are caller assertions; this API does not authenticate them or perform rights review, media QA, duration/alignment measurement, transfer or publication.

## Work tracking

- [Foundation #1](https://github.com/ootakazuhiko/NarraDock/issues/1)
- [Audio publication #2](https://github.com/ootakazuhiko/NarraDock/issues/2)
- [Isolation #3](https://github.com/ootakazuhiko/NarraDock/issues/3)
- [License and administration #4](https://github.com/ootakazuhiko/NarraDock/issues/4)
- [Core development #7](https://github.com/ootakazuhiko/NarraDock/issues/7) / [Codex handoff](docs/codex-handoff.md)

## License

The maintainer approved **NarraDock Source-Available License 1.0** on 2026-10-04. [Read the approved text and activation status](LICENSE.md). License selection is complete; the annexes and Article 20 activation remain incomplete. Do not claim an effective public license, publish a package under an assumed license, or invent fees. Dependency and contributor rights remain separate. This is not an OSI-approved open-source license.
