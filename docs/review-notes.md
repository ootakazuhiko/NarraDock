# Candidate-bound playback notes

The [candidate preview](candidate-preview.md) now lets a listener create private
notes at a playback position, edit/delete them, return to that position, and
explicitly download JSON. Saved JSON can initialize a newly generated preview
through the Python API below. These are unauthenticated notes for follow-up work,
not review-completion evidence or approval decisions. The synthetic demo has no
notes panel. No account, server, dependency, automatic storage or transfer is
required.

## Browser workflow

1. Open a candidate preview and select **この位置にメモ**. The current position
   and corresponding cue are fixed while text is entered. Playback is neither
   started nor stopped by this action; later playback/seek changes do not move
   the draft's anchor.
2. Enter text and select **メモを追加**, or cancel. Existing notes can be edited
   without changing their position, deleted, or selected to seek. Seeking keeps
   playback paused if it was paused and does not move keyboard focus.
3. Select **メモをJSONで保存**. It requests a local download named
   `narradock-review-notes.json`. The page cannot confirm that the browser saved
   it; check the browser's download result and destination. Repeated downloads
   and filename conflicts are handled by the browser.

The editor must be added/canceled before export, so a pending draft is not
silently omitted. Changes stay in page memory until the page closes or reloads;
there is no local/session storage or browser import UI. Reopening a generated
page restores only its embedded initial notes, not later edits, deletions or
additions. To keep those changes, export JSON and use it to generate a new preview.
A browser that supports unload
confirmation can warn while notes remain, including after a download request.
It also warns after all initially restored notes are deleted; that empty state
can be exported. This is not a recovery mechanism. Export failure retains the notes. A media
error disables new position capture and navigation but retains editing/export
of existing notes. Keyboard focus returns to an enabled control, or the notes
heading when no such control is available.

The anchor is an integer millisecond point, not a time range. Conversion floors
the media clock after snapping only floating-point representation noise near an
integer millisecond; it clamps to the declared duration. For example, seeking to
1.001 seconds must record 1001 ms even if binary multiplication yields
1000.9999999999999. A genuinely earlier 1.0009 seconds records 1000 ms. The
highlighting clock uses the same representation correction. Cue references use
the resulting integer and half-open `[start_ms, end_ms)` intervals. Leading,
internal and trailing gaps, and the declared end, use `null`.

## JSON contract: `candidate-review-notes-0.1`

Exact root fields:

| Field | Meaning |
|---|---|
| `schema_version` | `candidate-review-notes-0.1` |
| `project_id`, `content_id` | Selected candidate scope |
| `candidate_fingerprint` | Full selected version 0.2 candidate revision |
| `transcript_fingerprint` | Complete selected transcript revision |
| `notes` | Ordered array of `{at_ms, cue_id, text}` |

There are no title, transcript body, audio bytes, source path, author, timestamp,
verdict or permission fields. Text is user-authored and can itself contain
private information. Notes preserve insertion order; identical notes and
out-of-time-order entries are valid. Internal UI identifiers are not exported.
An empty notes array is valid data and establishes no review outcome. The UI
offers export when at least one note exists or when all initially restored notes
have been deleted, so a cleared snapshot can be saved. A preview that starts
empty does not offer export until a note exists.

Limits include equality: 100 notes, 1,000 Unicode code points per note and
512 KiB of UTF-8 JSON input/output. Astral emoji count as one code point; composed
emoji sequences can contain several. Text is preserved without trimming or
normalization. LF and tab are allowed. Other U+0000–U+001F controls, U+007F–U+009F
and lone surrogates are rejected. Whitespace-only text is rejected using the
fixed ECMAScript whitespace set, including NBSP, Unicode spacing characters,
U+2028/U+2029 and U+FEFF. Format characters and valid Unicode sequences otherwise
remain plain text. The textarea uses a UTF-16 limit of 2,000 code units to allow
1,000 astral code points; the application separately enforces the code-point
limit. Browser newline normalization can occur during text entry.

## Python validation

```python
from narradock_review import load_review_notes

notes = load_review_notes(
    json_bytes,
    candidate=selected_candidate,
    project_id=assigned_project_id,
    expected_fingerprint=selected_candidate_fingerprint,
    transcript=selected_transcript,
)
```

This API accepts a `bytes` object only and returns independent parsed data.
The trusted caller owns any bounded reading/persistence; the API never opens a
path or writes a file. It bounds input before decoding and rejects invalid
UTF-8/BOM, malformed JSON, duplicate keys at every level, NaN/Infinity, unknown or
missing fields, wrong types and invalid note text. Times must be exact integers
(not bool, float or string), between zero and the candidate duration inclusive.
Each `cue_id` must equal the selected transcript cue at that integer time, or
`null` when none applies.

The API independently snapshots the caller's candidate and transcript. It
requires candidate 0.2, the expected full candidate fingerprint, matching
project/content/audio identity/duration, matching language and the canonical
full transcript fingerprint. It then compares the note export's scope and both
fingerprints. Changing audio, title, credits, transcript text or timing rejects
an unchanged old export. Failure raises `ReviewNotesError` with
`Review notes could not be validated`, without supplied values or partial data.

Validation establishes **structure and selected-revision reference consistency
only**. It performs no asset read or media measurement. Anyone able to edit the
JSON can rewrite hashes and text to match another candidate; hashes do not prove
who wrote it, that playback occurred, or that its anchor was captured by this UI.
There is no signature, authorization policy or authenticated review history.

## Resume saved notes in a preview

```python
from narradock_preview import build_candidate_preview

html_bytes, receipt = build_candidate_preview(
    selected_candidate,
    project_id=assigned_project_id,
    expected_fingerprint=selected_candidate_fingerprint,
    transcript=selected_transcript,
    registry=asset_registry,
    project_root=trusted_project_root,
    review_notes=json_bytes,
)
```

The optional `review_notes` argument accepts the saved UTF-8 `bytes` directly;
omitting it or passing `None` starts without notes. The caller owns bounded
reading and saving in the private workspace. The API uses `load_review_notes`
before audio I/O, including its 512 KiB input limit and strict revision checks.
It rejects stale or invalid notes with the preview's fixed `PreviewError` and
returns no partial output. It also re-verifies and measures the current WAV
through the existing guarded read; saved notes cannot substitute for this check.

The initial notes preserve text, order, duplicates, millisecond positions and cue
references. They can be edited, navigated, deleted and exported through the same
controls as new notes. Opening the page does not seek, autoplay, move focus or
start a download. Empty snapshots are valid. Notes for an older candidate or
transcript are rejected rather than automatically migrated or merged.

The generated HTML contains a fixed copy of the initial notes. Browser changes
never rewrite that HTML or the source JSON; save the new export explicitly and
regenerate to retain them. Copying the HTML also copies the embedded private note
text. The HTML size/hash in the receipt covers the initial notes, but subsequent
browser edits are not reflected in that receipt. No receipt field or approval
flag changes meaning.

## Isolation and acceptance

Embedded note JSON is escaped for HTML raw-text context, including script-closing
text, and limited to 2 MiB after escaping within the 64 MiB complete preview.
Displayed notes use `textContent`, never markup or detected links. Export uses
a JSON Blob and a temporary object URL created only in the explicit button
handler. The URL is revoked after a delay, on replacement or on page hide. The
existing content policy stays unchanged; no broad `blob:` script/media/network
permission is added. A download is a local user action, not an external transfer
or publication. Real notes belong in the private project workspace, outside
Git, public CI and PR attachments.

The candidate, transcript, package and preview receipt schemas are unchanged.
Preview receipt approval flags remain false. The package API does not accept
notes as decision records, and this feature does not synthesize such records.
Authenticated decisions, policy selection, browser file import, A/B comparison and
regeneration planning remain separate increments.

Python and Node tests share neutral Unicode/anchor conformance cases. The
explicit `tests/check_review_browser.py` acceptance tool uses already installed
Playwright/Chromium and a synthetic candidate. It verifies fixed anchors,
editing/cancel/delete/seek, caps and focus, failure retention, actual download
bytes accepted by Python, stale-revision rejection, restoration from the actual
download, unchanged and edited re-export, full deletion with empty export, and
reopening the original embedded snapshot. The generated page is
served only from memory on loopback. Browser checks are separate from CI;
Safari, mobile devices, screen readers and real-media acceptance remain untested.
