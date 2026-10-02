# Security

NarraDock is pre-alpha and is not ready to handle production secrets or unattended publication.

Do not submit credentials, private media, internal destinations, customer data, or exploitable sensitive details in public issues, pull requests, or CI artifacts. The repository's private vulnerability-reporting channel has not yet been verified; setting it up is tracked in issue #4. Until a private channel is confirmed, do not send sensitive reports here.

The bootstrap reads one explicitly supplied manifest and prints structural validation or a symbolic plan. It does not resolve asset references or call external services. Future filesystem, synthesis, storage, and publication adapters require a separate security review.

The public-file allowlist and generic pattern checks are limited safeguards, not a comprehensive secret scanner or proof of information isolation. Human review, dependency review, and independent execution tests remain required. If sensitive data is accidentally published, stop further distribution and revoke affected credentials; deleting a file does not prove that copies are gone.
