"""Offline synthetic tests; no media, credentials, or external services."""
from __future__ import annotations

import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import narradock_transcript as transcript

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "timed-transcript.json"


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def reject(self, document):
        with self.assertRaises(transcript.TranscriptError):
            transcript.validate(document)

    def test_neutral_example(self):
        self.assertEqual(transcript.load_transcript(EXAMPLE), self.document)

    def test_no_input_mutation(self):
        before = copy.deepcopy(self.document)
        transcript.validate(self.document)
        transcript.fingerprint(self.document)
        transcript.to_webvtt(self.document)
        self.assertEqual(before, self.document)

    def test_top_level_unknown_and_missing_fields(self):
        for key in self.document:
            with self.subTest(missing=key):
                modified = copy.deepcopy(self.document)
                del modified[key]
                self.reject(modified)
        self.reject(dict(self.document, extra=True))

    def test_nested_unknown_and_missing_fields(self):
        for section in ("audio", "cue"):
            original = self.document["audio"] if section == "audio" else self.document["cues"][0]
            for key in [*original, "extra"]:
                with self.subTest(section=section, key=key):
                    modified = copy.deepcopy(self.document)
                    target = modified["audio"] if section == "audio" else modified["cues"][0]
                    if key == "extra":
                        target[key] = True
                    else:
                        del target[key]
                    self.reject(modified)

    def test_wrong_container_types(self):
        for value in (None, [], "text", 3, True):
            with self.subTest(value=value):
                self.reject(value)
                for key in ("audio", "cues"):
                    modified = copy.deepcopy(self.document)
                    modified[key] = value
                    self.reject(modified)

    def test_wrong_cue_container(self):
        self.document["cues"] = ["not-an-object"]
        self.reject(self.document)

    def test_schema(self):
        for value in ("0.1", None, True, {}):
            self.reject(dict(self.document, schema_version=value))

    def test_identifier_shape(self):
        for value in ("../sample", "https://example.invalid", "Sample", "a--b", "a" * 65, [], None):
            for key in ("project_id", "content_id"):
                with self.subTest(key=key, value=value):
                    self.reject(dict(self.document, **{key: value}))
            modified = copy.deepcopy(self.document)
            modified["audio"]["asset_id"] = value
            self.reject(modified)
            modified = copy.deepcopy(self.document)
            modified["cues"][0]["id"] = value
            self.reject(modified)

    def test_language_shape(self):
        for value in ("", "EN", "en_US", "e", "en-" + "a" * 30, []):
            self.reject(dict(self.document, language=value))
        transcript.validate(dict(self.document, language="ja"))
        transcript.validate(dict(self.document, language="en-US"))

    def test_digest_shape(self):
        for value in ("a" * 63, "A" * 64, "g" * 64, [], None):
            self.document["audio"]["sha256"] = value
            self.reject(self.document)

    def test_duration_restrictions(self):
        for value in (0, -1, True, 6000.0, float("nan"), transcript.MAX_DURATION_MS + 1):
            self.document["audio"]["duration_ms"] = value
            self.reject(self.document)

    def test_cue_integer_milliseconds(self):
        for key in ("start_ms", "end_ms"):
            for value in (True, 1.0, float("inf"), -1, "1000", None):
                modified = copy.deepcopy(self.document)
                modified["cues"][0][key] = value
                self.reject(modified)

    def test_zero_length_and_reversed_cues(self):
        for end in (0, 100):
            modified = copy.deepcopy(self.document)
            modified["cues"][0].update(start_ms=100, end_ms=end)
            self.reject(modified)

    def test_overlap_is_rejected(self):
        self.document["cues"][1]["start_ms"] = 1999
        self.reject(self.document)

    def test_unsorted_cues_are_not_silently_sorted(self):
        self.document["cues"].reverse()
        self.reject(self.document)

    def test_adjacent_cues_are_valid(self):
        self.document["cues"][1]["start_ms"] = 2000
        transcript.validate(self.document)

    def test_leading_internal_and_trailing_gaps_are_valid(self):
        self.document["cues"][0]["start_ms"] = 500
        transcript.validate(self.document)

    def test_end_at_duration_is_valid_but_beyond_is_not(self):
        self.document["cues"][-1]["end_ms"] = 6000
        transcript.validate(self.document)
        self.document["cues"][-1]["end_ms"] = 6001
        self.reject(self.document)

    def test_duplicate_ids(self):
        self.document["cues"][1]["id"] = "cue-one"
        self.reject(self.document)

    def test_cue_count_bounds(self):
        self.reject(dict(self.document, cues=[]))
        self.reject(dict(self.document, cues=[{}] * (transcript.MAX_CUES + 1)))

    def test_text_validation_and_block_injection(self):
        for value in ("", " ", " leading", "trailing ", "a\nb", "a\r\nb", "a\t b",
                      "a\x00b", "a\u202eb", "a\ud800b", "a\u2028b", "a\u2029b",
                      "a" * (transcript.MAX_TEXT + 1), [], None):
            with self.subTest(value=repr(value)):
                self.document["cues"][0]["text"] = value
                self.reject(self.document)

    def test_international_text(self):
        self.document["cues"][0]["text"] = "合成サンプル。"
        self.assertIn("合成サンプル。", transcript.to_webvtt(self.document))

    def test_webvtt_exact_timestamps_and_separator(self):
        actual = transcript.to_webvtt(self.document)
        self.assertTrue(actual.startswith("WEBVTT\n\ncue-one\n00:00:00.000 --> 00:00:02.000\n"))
        self.assertIn("cue-two\n00:00:02.500 --> 00:00:05.500\n", actual)
        self.assertTrue(actual.endswith("\n\n"))
        self.assertEqual(actual, transcript.to_webvtt(self.document))

    def test_webvtt_escape_plain_text(self):
        self.document["cues"][0]["text"] = '<b>A & B</b> --> &lt; "quote"'
        output = transcript.to_webvtt(self.document)
        self.assertIn('&lt;b&gt;A &amp; B&lt;/b&gt; --&gt; &amp;lt; "quote"', output)
        self.assertNotIn("<b>", output)

    def test_hour_and_millisecond_boundaries(self):
        self.document["audio"]["duration_ms"] = transcript.MAX_DURATION_MS
        self.document["cues"] = [{"id": "cue-hour", "start_ms": 3599999,
                                  "end_ms": transcript.MAX_DURATION_MS, "text": "Synthetic text."}]
        self.assertIn("00:59:59.999 --> 24:00:00.000", transcript.to_webvtt(self.document))

    def test_export_always_validates(self):
        self.document["cues"][0]["end_ms"] = -1
        with self.assertRaises(transcript.TranscriptError):
            transcript.to_webvtt(self.document)
        with self.assertRaises(transcript.TranscriptError):
            transcript.fingerprint(self.document)

    def test_fingerprint_ignores_object_key_order(self):
        reordered = dict(reversed(list(self.document.items())))
        self.assertEqual(transcript.fingerprint(self.document), transcript.fingerprint(reordered))

    def test_fingerprint_changes_with_text_timing_audio_and_scope(self):
        before = transcript.fingerprint(self.document)
        for target, key, value in (("cue", "text", "Revised synthetic text."),
                                   ("cue", "end_ms", 1900), ("audio", "sha256", "b" * 64),
                                   ("root", "project_id", "other-project"),
                                   ("root", "language", "ja")):
            modified = copy.deepcopy(self.document)
            node = modified["cues"][0] if target == "cue" else modified["audio"] if target == "audio" else modified
            node[key] = value
            self.assertNotEqual(before, transcript.fingerprint(modified))

    def test_matching_binding(self):
        expected = {key: copy.deepcopy(self.document[key]) for key in ("project_id", "content_id", "audio")}
        transcript.require_binding(self.document, expected)

    def test_changed_project_content_asset_digest_or_duration_binding(self):
        for target, key, value in (("root", "project_id", "other-project"),
                                   ("root", "content_id", "other-content"),
                                   ("audio", "asset_id", "other-audio"),
                                   ("audio", "sha256", "b" * 64),
                                   ("audio", "duration_ms", 6100)):
            expected = {name: copy.deepcopy(self.document[name]) for name in ("project_id", "content_id", "audio")}
            node = expected if target == "root" else expected["audio"]
            node[key] = value
            with self.assertRaisesRegex(transcript.TranscriptError, "binding mismatch"):
                transcript.require_binding(self.document, expected)

    def test_invalid_expected_binding(self):
        for expected in (None, {}, dict(project_id="sample-project", content_id="sample-content", audio={})):
            with self.assertRaises(transcript.TranscriptError):
                transcript.require_binding(self.document, expected)

    def test_duplicate_json_keys_at_all_levels(self):
        original = json.dumps(self.document)
        for raw in ('{"cues":[],"cues":[]}', original.replace('"asset_id":', '"asset_id":"duplicate", "asset_id":'),
                    original.replace('"id":', '"id":"duplicate", "id":', 1)):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "sample.json"
                path.write_text(raw, encoding="utf-8")
                with self.assertRaisesRegex(transcript.TranscriptError, "Duplicate JSON key"):
                    transcript.load_transcript(path)

    def test_invalid_file_inputs_and_bounds(self):
        for raw in (b"\xff", b"{", b"[]", b'{"value":NaN}', b'{"value":Infinity}',
                    b"[" * 2000 + b"]" * 2000, b" " * (transcript.MAX_BYTES + 1)):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "sample.json"
                path.write_bytes(raw)
                with self.assertRaises(transcript.TranscriptError):
                    transcript.load_transcript(path)

    def test_missing_file_does_not_echo_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample-private-marker.json"
            with self.assertRaises(transcript.TranscriptError) as caught:
                transcript.load_transcript(path)
            self.assertNotIn("sample-private-marker", str(caught.exception))
            self.assertNotIn(directory, str(caught.exception))

    def test_cli_structure_only_and_no_file_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.json"
            path.write_text(json.dumps(self.document), encoding="utf-8")
            before = path.read_bytes()
            result = subprocess.run([sys.executable, "-B", str(ROOT / "narradock_transcript.py"), "validate", str(path)],
                                    cwd=directory, capture_output=True, check=False)
            self.assertEqual(0, result.returncode, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual("structure_only", value["scope"])
            self.assertEqual(2, value["cue_count"])
            for key in ("media_verified", "binding_verified", "external_transfer", "publication"):
                self.assertIs(False, value[key])
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(["sample.json"], sorted(item.name for item in Path(directory).iterdir()))

    def test_cli_vtt_is_utf8(self):
        self.document["cues"][0]["text"] = "合成サンプル。"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.json"
            path.write_text(json.dumps(self.document), encoding="utf-8")
            environment = dict(os.environ, PYTHONIOENCODING="ascii")
            result = subprocess.run([sys.executable, "-B", str(ROOT / "narradock_transcript.py"), "vtt", str(path)],
                                    cwd=directory, capture_output=True, env=environment, check=False)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("合成サンプル。", result.stdout.decode("utf-8"))

    def test_cli_error_is_sanitized_and_stdout_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample-private-marker.json"
            path.write_text('{"private-value-marker":NaN}', encoding="utf-8")
            result = subprocess.run([sys.executable, "-B", str(ROOT / "narradock_transcript.py"), "validate", str(path)],
                                    cwd=directory, capture_output=True, check=False)
            self.assertEqual(2, result.returncode)
            self.assertEqual(b"", result.stdout)
            self.assertNotIn(b"private-value-marker", result.stderr)
            self.assertNotIn(b"sample-private-marker", result.stderr)

    def test_cli_closed_pipe_has_safe_output_error(self):
        large = copy.deepcopy(self.document)
        large["cues"] = [
            {"id": f"cue-{index}", "start_ms": index * 1000,
             "end_ms": (index + 1) * 1000, "text": "x" * transcript.MAX_TEXT}
            for index in range(6)
        ]
        for command, document in (("validate", self.document), ("vtt", self.document),
                                  ("vtt", large)):
            with self.subTest(command=command, text_length=len(document["cues"][0]["text"])):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "sample.json"
                    path.write_text(json.dumps(document), encoding="utf-8")
                    read_fd, write_fd = os.pipe()
                    os.close(read_fd)
                    try:
                        # Ignore PYTHONUNBUFFERED so small outputs exercise the flush.
                        result = subprocess.run(
                            [sys.executable, "-E", "-B", str(ROOT / "narradock_transcript.py"),
                             command, str(path)], cwd=directory, stdout=write_fd,
                            stderr=subprocess.PIPE, check=False, timeout=10)
                    finally:
                        os.close(write_fd)
                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertEqual([b"Invalid transcript: Output could not be written"],
                                     result.stderr.splitlines())

    def test_main_in_process(self):
        output = io.StringIO()
        with patch("sys.stdout", output):
            self.assertEqual(0, transcript.main(["vtt", str(EXAMPLE)]))
        self.assertTrue(output.getvalue().startswith("WEBVTT"))


if __name__ == "__main__":
    unittest.main()
