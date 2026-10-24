"""Synthetic note exports and reference checks; no real review decisions or media."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import narradock_candidates as candidates
import narradock_review as review
import narradock_transcript as transcripts

CASES = json.loads((Path(__file__).parent / "fixtures/review-notes-cases.json").read_text(encoding="utf-8"))


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.project = "sample-project"
        audio = {"asset_id": "sample-audio", "sha256": "b" * 64, "duration_ms": 6000}
        self.transcript = {"schema_version": transcripts.SCHEMA_VERSION,
            "project_id": self.project, "content_id": "sample-content", "language": "en",
            "audio": audio.copy(), "cues": [
                {"id": "first", "start_ms": 1000, "end_ms": 2000, "text": "First."},
                {"id": "second", "start_ms": 2000, "end_ms": 3000, "text": "Second."},
                {"id": "last", "start_ms": 4000, "end_ms": 5000, "text": "Last."}]}
        self.candidate = {"schema_version": candidates.TRANSCRIPT_SCHEMA_VERSION,
            "project_id": self.project, "content_id": "sample-content", "audio": {**audio, "size_bytes": 96044},
            "metadata": {"title": "Neutral review", "language": "en", "credits": ["Synthetic credit"]},
            "transcript": {"fingerprint": transcripts.fingerprint(self.transcript)}}
        self.revision = candidates.candidate_fingerprint(self.candidate, project_id=self.project)
        self.document = {"schema_version": review.SCHEMA_VERSION, "project_id": self.project,
            "content_id": "sample-content", "candidate_fingerprint": self.revision,
            "transcript_fingerprint": self.candidate["transcript"]["fingerprint"],
            "notes": [{"at_ms": 1500, "cue_id": "first", "text": "Neutral note."}]}

    def load(self, data=None, **kwargs):
        arguments = {"candidate": self.candidate, "transcript": self.transcript,
                     "project_id": self.project, "expected_fingerprint": self.revision}
        arguments.update(kwargs)
        return review.load_review_notes(json.dumps(self.document).encode() if data is None else data, **arguments)

    def reject(self, data=None, **kwargs):
        with self.assertRaisesRegex(review.ReviewNotesError, "^Review notes could not be validated$"):
            self.load(data, **kwargs)

    def test_round_trip_preserves_notes_and_opens_no_paths(self):
        original = copy.deepcopy(self.document)
        with patch("builtins.open", side_effect=AssertionError("No file I/O")):
            result = self.load()
        self.assertEqual(original, result)
        result["notes"][0]["text"] = "Changed result"
        self.assertEqual(original, self.document)
        self.assertEqual({"schema_version", "project_id", "content_id", "candidate_fingerprint",
                          "transcript_fingerprint", "notes"}, set(result))

    def test_empty_notes_are_valid_but_not_a_review_completion_claim(self):
        self.document["notes"] = []
        self.assertEqual([], self.load()["notes"])
        for field in ("approved", "human_reviewed", "rights_verified", "media_qa_passed", "publication", "opinion"):
            self.document[field] = True
            self.reject()
            del self.document[field]

    def test_shared_unicode_text_conformance_cases(self):
        for case in CASES["text_cases"]:
            with self.subTest(case=case["name"]):
                self.document["notes"][0]["text"] = case["text"]
                if case["valid"]:
                    self.assertEqual(case["text"], self.load()["notes"][0]["text"])
                else:
                    self.reject()

    def test_shared_anchor_boundaries_and_wrong_cue_associations(self):
        for anchor in CASES["anchor_cases"]:
            with self.subTest(anchor=anchor):
                self.document["notes"][0].update(anchor)
                self.assertEqual(anchor["cue_id"], self.load()["notes"][0]["cue_id"])
                self.document["notes"][0]["cue_id"] = "first" if anchor["cue_id"] is None else None
                self.reject()

    def test_note_order_and_identical_notes_are_preserved(self):
        first = self.document["notes"][0]
        self.document["notes"] = [dict(at_ms=6000, cue_id=None, text="End."), first, first.copy()]
        self.assertEqual(self.document, self.load())

    def test_note_text_and_count_limits_include_equality(self):
        note = self.document["notes"][0]
        for char in ("x", "🎵"):
            note["text"] = char * review.MAX_TEXT
            self.assertEqual(note["text"], self.load()["notes"][0]["text"])
            note["text"] += char
            self.reject()
        note["text"] = "🎵" * review.MAX_TEXT
        self.document["notes"] = [note.copy() for _ in range(review.MAX_NOTES)]
        # UTF-8 astral text uses four bytes per scalar, not JSON ASCII escapes.
        data = json.dumps(self.document, ensure_ascii=False).encode("utf-8")
        self.assertEqual(review.MAX_NOTES, len(self.load(data)["notes"]))
        self.document["notes"].append(note.copy())
        self.reject(json.dumps(self.document, ensure_ascii=False).encode("utf-8"))

    def test_bounded_utf8_bytes_and_duplicate_keys(self):
        data = json.dumps(self.document).encode()
        padded = data + b" " * (review.MAX_BYTES - len(data))
        self.assertEqual(self.document, self.load(padded))
        for bad in (padded + b" ", b"", b"\xff", b"\xef\xbb\xbf" + data,
                    data.decode(), bytearray(data), b"[]", b"null", b"[" * 10000,
                    b'{"notes":[],"notes":[]}',
                    data.replace(b'"at_ms": 1500', b'"at_ms": 1500, "at_ms": 1500')):
            with self.subTest(kind=type(bad).__name__):
                self.reject(bad)

    def test_invalid_time_types_and_nonfinite_numbers(self):
        for value in (True, False, -1, 6001, 1500.0, "1500", None, float("nan"), float("inf")):
            self.document["notes"][0]["at_ms"] = value
            with self.subTest(value=value):
                self.reject()

    def test_unknown_missing_fields_and_invalid_containers(self):
        for key in tuple(self.document):
            original = self.document.pop(key)
            self.reject()
            self.document[key] = original
        original = self.document["notes"]
        for bad in (None, {}, "notes", [None], [[]], [{}], [dict(original[0], extra=True)]):
            self.document["notes"] = bad
            self.reject()
        self.document["notes"] = original
        for key in tuple(original[0]):
            value = original[0].pop(key)
            self.reject()
            original[0][key] = value
        for value in (True, 0, "unknown-cue", ""):
            original[0]["cue_id"] = value
            self.reject()

    def test_all_scope_and_revision_fields_must_match(self):
        for key in ("schema_version", "project_id", "content_id", "candidate_fingerprint", "transcript_fingerprint"):
            original = self.document[key]
            self.document[key] = "another-value"
            self.reject()
            self.document[key] = original
        self.reject(project_id="another-project")
        self.reject(expected_fingerprint="a" * 64)

    def test_unchanged_notes_reject_changed_title_credits_and_audio(self):
        original = copy.deepcopy(self.candidate)
        for section, key, value in (("metadata", "title", "New title"), ("metadata", "credits", []),
                                    ("audio", "sha256", "a" * 64), ("audio", "size_bytes", 96046)):
            self.candidate = copy.deepcopy(original)
            self.candidate[section][key] = value
            revision = candidates.candidate_fingerprint(self.candidate, project_id=self.project)
            self.reject(expected_fingerprint=revision)

    def test_changed_transcript_text_and_timing_invalidate_old_notes(self):
        for field, value in (("text", "Changed."), ("end_ms", 1999)):
            with self.subTest(field=field):
                self.setUp()
                self.transcript["cues"][0][field] = value
                self.candidate["transcript"]["fingerprint"] = transcripts.fingerprint(self.transcript)
                self.revision = candidates.candidate_fingerprint(self.candidate, project_id=self.project)
                self.reject()

    def test_refingerprinted_cross_binding_still_rejects(self):
        original = copy.deepcopy(self.transcript)
        for section, key, value in ((None, "project_id", "other-project"), (None, "content_id", "other-content"),
                (None, "language", "ja"), ("audio", "asset_id", "other-audio"),
                ("audio", "sha256", "a" * 64), ("audio", "duration_ms", 6001)):
            self.transcript = copy.deepcopy(original)
            target = self.transcript if section is None else self.transcript[section]
            target[key] = value
            self.candidate["transcript"]["fingerprint"] = transcripts.fingerprint(self.transcript)
            self.revision = candidates.candidate_fingerprint(self.candidate, project_id=self.project)
            self.document.update(candidate_fingerprint=self.revision,
                                 transcript_fingerprint=self.candidate["transcript"]["fingerprint"])
            with self.subTest(key=key):
                self.reject()

    def test_legacy_and_custom_candidate_inputs_reject(self):
        class Custom(dict):
            def __deepcopy__(self, memo):
                raise AssertionError("No caller hook")
        self.reject(candidate=Custom(self.candidate))
        self.reject(transcript=Custom(self.transcript))
        self.candidate["schema_version"] = candidates.SCHEMA_VERSION
        del self.candidate["transcript"], self.candidate["audio"]["duration_ms"]
        self.revision = candidates.candidate_fingerprint(self.candidate, project_id=self.project)
        self.reject()


if __name__ == "__main__":
    unittest.main()
