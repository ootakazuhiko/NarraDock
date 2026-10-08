# Product roadmap

## Decisions

NarraDock is a public personal product at `ootakazuhiko/NarraDock`. It is not an organization-owned private deployment. The name, repository, audio-first direction, and project isolation are established. The maintainer approved NarraDock Source-Available License 1.0 on 2026-10-04; [LICENSE.md](../LICENSE.md) records the approved terms and pending Article 20 activation. License selection is complete; annex completion and activation remain separate work in #4. Distribution namespace, audio engine, rendering backend, first publication destination, real execution environment, and live service accounts remain open decisions.

## Delivery slices

| Slice | Scope | Status |
|---|---|---|
| Foundation (#1) | Product docs, strict manifest validation, symbolic planning, neutral examples, CI | Bootstrap implementation proposed; follow PR/checks for live status |
| Audio publication (#2) | Intake contract, local package, destination adapter, reconciliation | Direction and acceptance defined; not implemented |
| Isolation (#3) | Public-file checks, asset/credential boundaries, independent acceptance | Limited static checks proposed; runtime isolation pending |
| Maintainer setup (#4) | License activation, rules, security intake, distribution decisions | License terms approved; activation and remaining administration pending |
| Media execution | Existing-audio import, synthesis/render adapters, measured QA, review | Planned; separate scoped PRs required |

First complete one neutral audio-only local-package workflow, then a second neutral video-enabled workflow. Do not delay generic local development solely because a publication provider has not been selected. Do not turn operational content into framework fixtures.

A code merge, installed version, successful render, human acceptance, and public release are different states. No release date, throughput target, production readiness, or external publication is asserted here.
