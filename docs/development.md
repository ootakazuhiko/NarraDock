# Development validation

## Preconditions

Executor: the assigned developer or CI job. Repository: `ootakazuhiko/NarraDock`. Use a dedicated checkout/worktree, Python 3.11+, and Git. No media, provider service, credentials, package installation, or deployment is required.

Before a local session, record the exact absolute checkout/worktree path, OS/shell, base branch `main`, assigned feature branch and PR, actual HEAD, clean/dirty state, running processes, permitted files, prohibited locations, and timing. No production or Windows worktree is preassigned by this document. Missing assignment means stop; do not guess a Windows path or reuse an unrelated checkout.

The initial development branch is `chore/public-product-bootstrap`. Read the live PR for the proposed HEAD; do not infer current status from a historic document. For subsequent changes use a newly assigned branch/PR. Do not write main or contact providers.

## Validation sequence

Run from the confirmed repository root in the assigned shell. Commands below are validation commands, not a Windows deployment instruction. New files must be staged to the assigned branch's index for the tracked-file inventory check; inspect the allowlist and diff before staging. In CI all files are already tracked.

```text
python -B -m unittest discover -s tests -v
python -B tools/check_public_tree.py
python -B narradock.py validate examples/audio-only.json
python -B narradock.py plan examples/audio-only.json
python -B narradock.py plan examples/video-enabled.json
git diff --check
```

Stop after any nonzero exit. Expected: all tests pass; public surface check passes; validation says `structure_only`; both plans say `plan_only` and all execution/transfer/publication flags remain false. The audio-only plan contains no video-render step. No assets are created, resolved, synthesized, or uploaded. Test temporary directories are synthetic and automatically removed. `-B` prevents bytecode output. Tracked content should be unchanged by validation.

## Failure and recovery

Validation errors return exit 2 for the CLI and exit 1 for the public-tree checker. Do not include an actual manifest, credential, local path, or environment dump in public diagnostics. Report command, exit code, sanitized category, and the assigned revision. Preserve needed evidence in the session's approved private evidence location, which must be assigned before real-data work.

Read-only validation needs no Git restore. For a rejected source change, preserve the assigned diff privately, then correct only the assigned files or abandon the unmerged PR. After merge use a reviewed correction/revert PR. Never reset main, force-push, delete unrelated work, or remove evidence to obtain a pass.

## CI

NarraDock CI runs Python tests, inventory checks, and example commands on Linux and Windows. Actions are pinned to full upstream commit SHAs and the token has `contents: read`; checkout does not persist credentials. There are no media-provider calls, release steps, artifact uploads, or publishing credentials. CI success is not production acceptance or publication permission.
