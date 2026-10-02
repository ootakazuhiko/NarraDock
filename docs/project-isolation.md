# Project and public-source isolation

Only generic source code, neutral documentation, and newly authored synthetic examples belong in this repository. User scripts, recordings, pictures, videos, brands, real voice profiles, local paths, private account identifiers, access tokens, reviews, and runtime evidence do not.

Keep each project's asset registry, cache, working directory, locks, credentials, permissions, and release history isolated. The shared tool's read access must not grant access to other projects. Future adapters must reject traversal, symlink/junction escape, accidental shared-cache reuse, and implicit credential fallback. These runtime controls are not implemented by the bootstrap's text validator.

Public distribution starts from an explicit file allowlist, never a whole workstation folder or copied unrelated Git history. Check filenames, comments, fixtures, package metadata, build output, source maps, URLs, release notes, issue/PR bodies, and media metadata. Public checks must not include private identifier lists or sensitive findings. Keep sensitive audits outside the repository.

The current tools/check_public_tree.py verifies the tracked-file inventory, simple text/type/size constraints, and a few generic credential/path patterns. It does not inspect all possible secrets, prove semantic neutrality, audit Git history, verify licenses, or enforce a runtime sandbox. The CLI reads the manifest file explicitly supplied by its caller; future project-root access control is a separate implementation.

Distribution approval additionally requires human review and a clean-environment run using only allowed source plus neutral samples. Repeat checks for every update. Do not claim that deleted public information has been completely recalled.
