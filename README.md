# NarraDock

**Scripts to audio and video, with review and publication kept under control.**

NarraDock is a public personal product for reusable media-production workflows. Audio-only publication is a first-class path, not a side effect of video production.

[日本語](README.ja.md) · [Architecture](docs/architecture.md) · [Audio publication](docs/audio-publication.md) · [Roadmap](docs/roadmap.md)

## Status: pre-alpha

Implemented in the bootstrap: strict manifest validation, deterministic **symbolic planning**, neutral examples, unit tests, and a public-source inventory check. Python 3.11+ and Git are sufficient for these checks; no third-party Python packages are required.

**Not implemented:** asset resolution/hash verification, synthesis, media rendering, media QA, review UI, release packaging, upload, RSS generation, or publication. Plan entries name future operations; the CLI never performs them and never records approval. Example hashes are placeholders, not verified media fingerprints.

## Product boundaries

Shared code and neutral examples belong here. Project scripts, media, brands, voice selections, operational credentials, reviews, caches, logs, and publication records belong in isolated user workspaces. This repository is not a content-hosting location.

Production, technical QA, human review, candidate selection, external transfer, and publication are separate decisions. Public source visibility grants none of those operational permissions.

## Development entry

Read [development prerequisites and validation](docs/development.md) before running the bootstrap CLI. The two examples demonstrate existing-audio reuse and a script-to-video proposal without contacting an audio engine or publisher.

The initial version is `0.1.0a1`; no installable package or release has been published. Runtime data must not be committed even when ignored files can be force-added.

## Work tracking

- [Foundation #1](https://github.com/ootakazuhiko/NarraDock/issues/1)
- [Audio publication #2](https://github.com/ootakazuhiko/NarraDock/issues/2)
- [Isolation #3](https://github.com/ootakazuhiko/NarraDock/issues/3)
- [License and administration #4](https://github.com/ootakazuhiko/NarraDock/issues/4)

## License

A software license has not yet been selected. Do not describe the product as licensed open-source software or publish a package under an assumed license. Dependency and media rights are independent decisions.
