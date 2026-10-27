# Development validation

## Preconditions

Executor: the assigned developer or CI job. Repository: `ootakazuhiko/NarraDock`. Use a dedicated checkout/worktree, Python 3.11+, Node.js 20+ for player controller tests, and Git. No media, provider service, credentials, package installation, or deployment is required.

Before a local session, record the exact absolute checkout/worktree path, OS/shell, base branch `main`, assigned feature branch and PR, actual HEAD, clean/dirty state, running processes, permitted files, prohibited locations, and timing. No production or Windows worktree is preassigned by this document. Missing assignment means stop; do not guess a Windows path or reuse an unrelated checkout.

The initial development branch is `chore/public-product-bootstrap`. Read the live PR for the proposed HEAD; do not infer current status from a historic document. For subsequent changes use a newly assigned branch/PR. Do not write main or contact providers.

## Validation sequence

Run from the confirmed repository root in the assigned shell. Commands below are validation commands, not a Windows deployment instruction. New files must be staged to the assigned branch's index for the tracked-file inventory check; inspect the allowlist and diff before staging. In CI all files are already tracked.

```text
python -B -m unittest discover -s tests -v
node --test tests/test_player.cjs
python -B tools/check_public_tree.py
python -B narradock.py validate examples/audio-only.json
python -B narradock.py plan examples/audio-only.json
python -B narradock.py plan examples/video-enabled.json
git diff --check
```

Stop after any nonzero exit. Expected: all tests pass; public surface check passes; validation says `structure_only`; both plans say `plan_only` and all execution/transfer/publication flags remain false. The audio-only plan contains no video-render step. The manifest CLI example commands create, resolve, synthesize or upload no assets. Test temporary directories are synthetic and automatically removed. `-B` prevents bytecode output. Tracked content should be unchanged by validation.

The [script-block contract](script-contract.md) is covered by the same discovered
Python suite. Its tests use neutral in-memory text and the tracked example to
check parsing/bounds, preserved Unicode and line endings, full/body revision
identity, selection rejection and non-execution of directives. They do not
require a speech engine or browser. Browser checks below remain separate
evidence for changes to the player; they are not script-adapter acceptance.

## Failure and recovery

Validation errors return exit 2 for the CLI and exit 1 for the public-tree checker. Do not include an actual manifest, credential, local path, or environment dump in public diagnostics. Report command, exit code, sanitized category, and the assigned revision. Preserve needed evidence in the session's approved private evidence location, which must be assigned before real-data work.

Read-only validation needs no Git restore. For a rejected source change, preserve the assigned diff privately, then correct only the assigned files or abandon the unmerged PR. After merge use a reviewed correction/revert PR. Never reset main, force-push, delete unrelated work, or remove evidence to obtain a pass.

## CI

NarraDock CI runs Python tests, Node standard-library player controller tests, inventory checks, and example commands on Linux and Windows. Node is provided by the hosted runner image; no npm packages are installed. Actions are pinned to full upstream commit SHAs and the token has `contents: read`; checkout does not persist credentials. There are no media-provider calls, release steps, artifact uploads, or publishing credentials. CI success is not production acceptance or publication permission.

## Explicit browser acceptance

The [synthetic player](standalone-player.md) has a separate `tests/check_player_browser.py` acceptance tool using an already installed Playwright and selected Chromium executable. This optional development capability is not a runtime dependency and is not installed automatically. Run it only in an assigned environment; record the browser version, outcomes and any screenshots privately. Node/Python CI does not establish browser compatibility. The tool serves one generated in-memory page on loopback and does not expose working-directory files. Safari, mobile devices, screen readers and real-media acceptance require separate evidence.

Transcript-search acceptance includes explicit search/selection, literal text,
Unicode bounds, keyboard focus, playing/paused navigation, stale results,
reload/error gating and narrow layout. IME composition events are simulated;
native OS input-method behavior still needs separate acceptance. Candidate and
review browser tools verify search against verified previews and its coexistence
with pending/restored notes. No search text or result is persisted or uploaded.

`tests/check_preview_browser.py` uses the same browser setup to verify a [candidate preview](candidate-preview.md) built from generated tones and a matching synthetic registry/candidate/transcript. It checks actual playback, selected-byte identity, literal metadata, synchronization and narrow-screen layout. Both tools accept `--browser-executable` and an optional private `--screenshots` directory. Neither accepts real project data.

`tests/check_review_browser.py` uses the same arguments and synthetic setup for [playback notes](review-notes.md). It checks frozen anchors, editing/navigation, Unicode limits, focus at the count limit, export failure retention, and a real JSON download validated against the original candidate by Python. It then regenerates a preview from those downloaded bytes and checks restored literal text, editing/navigation, unchanged and edited re-export, empty export after deleting all restored notes, and reopening the embedded snapshot without automatic persistence. Its optional output directory also retains the synthetic JSON exports. No real review evidence is used or uploaded.
