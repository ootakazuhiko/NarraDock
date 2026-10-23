# Synthetic synchronized player

`narradock_player.py` renders a self-contained HTML demo of the [synchronized player contract](synchronized-playback.md). It contains a newly generated 24-second mono PCM WAV, its own validated timed transcript, and inline CSS/JavaScript. Short, quiet test tones mark cue starts; they are not spoken versions of the displayed sentences. This increment is for exercising playback controls and synchronization with public synthetic data.

No file/URL import, real-media review, candidate approval, package loading, authentication, external service, upload or deployment is implemented. Existing candidates, transcripts, measurements, package formats and placeholder examples remain unchanged. A later candidate-aware preview must bind and verify its selected inputs separately; it must not require a review-approved release package before the user can review it.

## Generate and open

Python 3.11+ is sufficient to generate the page; no Node process or server is needed by the page itself. Keep `narradock_player.py`, `narradock_transcript.py` and the tracked `player/` source files together. The public API takes no arguments:

```python
from narradock_player import render_demo

html = render_demo()
```

The caller can explicitly save this string as UTF-8 HTML in its assigned output area and open it in a browser. The CLI `python -B narradock_player.py` writes UTF-8 HTML bytes to stdout and accepts no arguments; it does not choose a destination, create a file or launch a browser. A caller redirecting stdout must preserve UTF-8 bytes, particularly in shells that transcode output. Reopening the page starts a fresh session at zero with no saved playback position.

The generated page embeds audio as a data URL and contains no resource URLs, uploads, cookies, local/session storage, analytics or external fonts. A content policy permits only the exact inline script/style hashes and embedded audio, with network connections, object embedding, form submission and base-URL changes disabled. Supplied script data is escaped for HTML raw-text context, and the player inserts cue text using `textContent`. These measures do not constitute entitlement or copy protection: this synthetic page can be copied and saved.

Some managed browsers forbid file URLs. The explicit browser test serves only the in-memory synthetic HTML at one loopback route; it never serves repository directories or arbitrary files. Direct file-opening behavior under such a policy is not asserted by that test.

## Controls and timing

- Native audio controls provide play/pause, seek and volume. There is no autoplay. Additional controls remain disabled until metadata is ready.
- Playback-rate choices are 0.75, 1, 1.25, 1.5 and 2. Native audio controls can offer additional rates; the select reflects their current value too. The displayed clock and active cue always derive from `audio.currentTime`; animation frames only request redraws, never advance an independent clock.
- Each cue is a button that seeks to its start without starting paused media or pausing playing media. Cue intervals are half-open `[start_ms, end_ms)`. Leading/internal/trailing gaps and media end have no highlighted cue. Pausing retains the cue at the current position.
- Media events, seeks, rate changes and visibility/page restoration re-evaluate the clock. Animation callbacks stop when paused, ended, hidden or waiting for new metadata. Media reload clears readiness and highlighting until metadata arrives. A decode/control error or unexpected synthetic duration clears highlighting and disables navigation with a fixed message.
- Auto-follow scrolls only the transcript container when the active cue changes. Wheel, touch, pointer, keyboard navigation or focus entering the transcript stops follow. It stays off until the user explicitly checks the control again. Manual navigation still updates highlighting and the clock. No automatic focus movement occurs.

The page has Japanese control labels, native keyboard controls, cue buttons with time labels, visible focus, `aria-current` on the active cue, wrapping text and a narrow-screen layout. Only deliberate follow changes and failures use the polite status region; clock/cue updates are not live announcements. Scrolling is instant, with reduced-motion styles and no animated waveform. Screen-reader/device acceptance remains separate from these code-level provisions.

## Validation boundaries

Run the normal Python sequence in [development.md](development.md), followed by `node --test tests/test_player.cjs` using Node.js 20+. No npm packages are required. Linux/Windows CI explicitly runs both suites. Python tests check fixture bytes/duration using the existing PCM measurement API, transcript validity, safe embedding, content-policy hashes, UTF-8 CLI behavior and source inventory. Node tests exercise half-open lookup, event-driven controller state, pause/seek/rate, metadata/errors, follow, visibility and cancellation without substituting for a real media element.

`tests/check_player_browser.py` is a separate explicit acceptance tool. It requires an already installed Python Playwright and an explicitly selected Chromium executable. It never installs packages or browsers. Its arguments are `--browser-executable` and an optional `--screenshots` directory in the assigned private evidence area. It serves only generated synthetic HTML on a temporary loopback port, blocks other HTTP requests, checks real media clock advance and native controls, and optionally saves screenshots. It is not part of default unittest discovery or hosted CI; absence of this run must not be reported as a browser pass.

Browser cases cover adjacency/gaps/end, paused cue navigation, native keyboard play/pause, rate changes, actual end, follow/manual scrolling, focus preservation, visible focus, literal markup-looking text, no external resource requests, media failure, reduced-motion mode and a narrow viewport. Node tests cover hidden-tab scheduling; dispatching a visibility event in the browser is only a wiring check, not proof of background-tab throttling behavior.

Current acceptance is limited to the recorded desktop Chromium version and simulated viewport. Safari, Firefox, mobile devices, assistive technologies, audibility/quality with real recordings, background resource suspension and entitlement delivery remain untested. Synthetic control checks do not approve media quality, rights, human review or publication.
