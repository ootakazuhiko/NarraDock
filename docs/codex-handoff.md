# Codex product-development handoff

This is a work-package plan, not a launched session or a Windows execution instruction. Owner-requested development concerns only `ootakazuhiko/NarraDock`. Issue #7 defines the next implementation increment.

## Recommended assignment

Use a new Codex cloud task for the generic core and offline tests. Use the desktop app for later interactive UI/browser iteration and code review. Use a separately assigned native Windows Codex CLI session for later installed-engine and local filesystem acceptance. These are workflow choices, not differences in code ownership; only one writer may operate a branch. A local client still uses model inference services, so local execution must not be described as a guarantee that context never leaves the device.

No production content, credentials, private data, existing local engine, unrelated repository or account is needed for the first cloud task. Restrict repository access to NarraDock and begin with no runtime internet access or application secrets. Dependency setup and task network access are separate settings. The initial Python implementation uses the standard library; do not install additional packages automatically.

## Known repository state and integration order

Observed on 2026-10-04, not a permanent HEAD assignment:

| Work | Branch | Revision | State at observation |
|---|---|---|---|
| Landing page | `main` | `a720ace8cc62ede8d56906d956e731a1058498ff` | No core implementation |
| Foundation PR #5 | `chore/public-product-bootstrap` | `135549f1713300fabfb0810ad019d0cebbf02d27` | Open Draft |
| Audio contract PR #6 | `feat/synchronized-audio-contract` | `793f337c723360347ca93e8b80719699346394e7` | Open Draft, based on #5 |
| Approved license and this handoff | `docs/license-adoption-codex-handoff` | Read the live PR | Based on #5; does not alter #5 or #6 |

The owner must separately review integration. Do not interpret license approval as permission to merge unrelated implementation PRs. First integrate #5 after review, then retarget the license/handoff PR to `main` and revalidate. PR #6 can then be retargeted and integrated under its own review. If both branches add inventory entries, retain the union in `public-files.json`; do not lose audio files, license files, or existing tests. Never merge the license or audio work into the bootstrap work branch.

Issue #7 starts from reviewed `main` containing the foundation and this handoff. The asset-registry increment does not require #6 to be merged, but must not modify or duplicate #6. The future synchronized player does depend on #6. A read-only review of the open stack can precede merges; feature writes cannot silently substitute a different base.

## Session preconditions — fill from observation before writes

Executor: a newly launched Codex task explicitly assigned to Issue #7. Do not append it to an audio implementation session.

Checkout/worktree: record the actual absolute path supplied by the selected cloud environment. Use an independently assigned checkout/worktree. The path and local process state are not known at document creation. No Windows checkout is assigned. Observe the repository root, remote, HEAD, branch, index/worktree state, task identity, allowed temporary directory, and relevant process ownership before writing. Unknown is not clean or stopped. Refuse an unrelated remote or a dirty/unowned checkout.

Base: refreshed `main` after the integration prerequisites. Work branch: `feat/core-asset-registry` if unowned and available; otherwise stop for reassignment. Target PR: a new focused Draft PR for Issue #7; record its actual number when created. Never reuse PR #5, PR #6 or the license PR.

Instruction file: `docs/codex-handoff.md` in that exact confirmed checkout. Record its resolved absolute filename and revision in the private task log. That new Issue #7 session is its reader. A task-specific execution record must include exact allowed/prohibited paths, backup destination and ordered commands; do not publish private workstation paths or raw environment output.

Timing: after the maintainer launches the selected client and the base is ready. This document does not create a cloud environment, start Codex, merge PRs or reserve an existing local process.

## First increment: verified local assets

Implement only a strict, bounded, versioned project-local asset registry and read-only resolution/verification. Scoped opaque identifiers resolve through explicit relative paths beneath the assigned project root. Verify actual bytes with streamed SHA-256 and size checks; never infer verification from a supplied digest. Reject project mismatch, duplicates, ambiguous references, traversal, absolute or redirected paths, links/reparse points that escape the boundary, non-regular files, mismatched bytes and detected input changes. Document race limitations and the trusted-root assumption instead of claiming OS-level sandbox enforcement.

Suggested added files: `narradock_assets.py`, `tests/test_assets.py`, `docs/asset-registry.md`, `examples/asset-registry.json`. Update `public-files.json`. Use generated neutral temporary bytes for tests, not real media. Two projects using the same asset ID must remain independent. Existing-audio handling must not invoke synthesis or require a video path.

Do not change `narradock.py` contracts, `narradock_transcript.py`, synchronized-playback work, existing tests/checkers/CI, approved license material, or other workstreams without an explicit updated scope. A new dependency or an existing-code integration requirement must be surfaced rather than hidden in a broad refactor.

## Validation and expected result

After paths/branch ownership are confirmed, use the ordered validation sequence in `docs/development.md` from the assigned root. Run the entire discovered test suite, not just new tests. The foundation has 35 tests; #6 adds 38 tests; license snapshot tests are additional. These are historic counts, not hard-coded success criteria. Record the actual test count, failures/skips, base/head, files changed and public inventory result.

Require successful Linux and Windows CI for the exact proposed HEAD. Report unexercised platform/race cases explicitly. No fake success, silent weakening, provider calls, real media generation, external transfer, billing, permission changes or publication. The result is a Draft PR plus actual evidence, not an automatic merge or production deployment.

## Error branches and recovery

On ownership, source, branch, cleanliness or permissions mismatch, stop before writes. On failed tests, correct only assigned changes; preserve sanitized diagnostic categories and keep private evidence outside Git. Remote movement requires refreshed verification, not force-push. Preserve the assigned diff at an explicitly recorded private backup path before restoring only assigned files. Do not reset main, delete other worktrees or remove failed outputs. An unmerged proposal can be abandoned without rolling back production. A merged error requires a reviewed correction/revert PR.

## Next increments

After Issue #7: candidate-bound local release packaging; a neutral synchronized player reusing #6; then a separately authorized local-engine adapter and a selected publication adapter. Keep transfer permission, public activation, media QA, playback review and software-license activation separate.

## Official client references

Checked 2026-10-04. Product labels and interfaces can change; use these official entry points rather than assuming a particular installed version.

- Cloud tasks: https://developers.openai.com/codex/cloud
- Cloud environments: https://developers.openai.com/codex/cloud/environments
- Desktop worktrees: https://developers.openai.com/codex/app/worktrees
- CLI: https://developers.openai.com/codex/cli
- Native Windows: https://developers.openai.com/codex/windows
