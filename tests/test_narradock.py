import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import narradock

ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "examples/audio-only.json").read_text(encoding="utf-8"))

    def test_audio_example(self):
        narradock.validate(self.data)

    def test_video_example(self):
        value = narradock.load_manifest(ROOT / "examples/video-enabled.json")
        self.assertIn("render_video", narradock.plan(value)["steps"])

    def test_audio_has_no_video_dependency(self):
        result = narradock.plan(self.data)
        self.assertNotIn("render_video", result["steps"])
        self.assertNotIn("visual_profile", result["unverified_requirements"])

    def test_existing_audio_is_not_resynthesized(self):
        self.assertNotIn("synthesize_audio", narradock.plan(self.data)["steps"])

    def test_script_requires_explicit_future_authority(self):
        self.data["source"]["kind"] = "script"
        result = narradock.plan(self.data)
        self.assertIn("generation_authorization", result["unverified_requirements"])
        self.assertFalse(result["executes_steps"])

    def test_no_network_or_publication(self):
        with patch("socket.create_connection", side_effect=AssertionError("Network forbidden")):
            result = narradock.plan(self.data)
        self.assertFalse(result["external_transfer"])
        self.assertFalse(result["publication"])

    def test_plan_is_deterministic(self):
        self.assertEqual(narradock.plan(self.data), narradock.plan(dict(reversed(list(self.data.items())))))

    def test_input_is_not_mutated(self):
        saved = copy.deepcopy(self.data)
        narradock.plan(self.data)
        self.assertEqual(saved, self.data)

    def test_changed_content_invalidates_fingerprint(self):
        old = narradock.plan(self.data)["plan_fingerprint"]
        self.data["source"]["sha256"] = "b" * 64
        self.assertNotEqual(old, narradock.plan(self.data)["plan_fingerprint"])

    def test_changed_metadata_invalidates_fingerprint(self):
        old = narradock.plan(self.data)["plan_fingerprint"]
        self.data["title"] = "Another neutral example"
        self.assertNotEqual(old, narradock.plan(self.data)["plan_fingerprint"])

    def test_unknown_fields_rejected(self):
        for key in ("credentials", "approved", "command", "endpoint"):
            with self.subTest(key=key):
                value = copy.deepcopy(self.data)
                value[key] = "untrusted"
                with self.assertRaises(narradock.ManifestError):
                    narradock.validate(value)

    def test_bad_root_rejected(self):
        for value in (None, [], True, "text", {}):
            with self.subTest(value=value), self.assertRaises(narradock.ManifestError):
                narradock.validate(value)

    def test_bad_ids_rejected(self):
        for value in ("../sample", "/sample", "sample/example", "sample\\example", "https://example.invalid", "", True, "a" * 65):
            with self.subTest(value=value):
                self.data["source"]["asset_id"] = value
                with self.assertRaises(narradock.ManifestError):
                    narradock.validate(self.data)

    def test_bad_outputs_rejected(self):
        for value in ([], ["audio", "audio"], ["upload"], [True], [{}], "audio"):
            with self.subTest(value=value):
                self.data["outputs"] = value
                with self.assertRaises(narradock.ManifestError):
                    narradock.validate(self.data)

    def test_bad_title_rejected(self):
        for value in ("", " leading", "line\nbreak", "a" * 201, "hidden\u202etext", False):
            with self.subTest(value=value):
                self.data["title"] = value
                with self.assertRaises(narradock.ManifestError):
                    narradock.validate(self.data)

    def test_bad_digest_rejected(self):
        for value in ("a" * 63, "G" * 64, True, []):
            with self.subTest(value=value):
                self.data["source"]["sha256"] = value
                with self.assertRaises(narradock.ManifestError):
                    narradock.validate(self.data)

    def test_public_mode_rejected(self):
        self.data["publication"]["mode"] = "public"
        with self.assertRaises(narradock.ManifestError):
            narradock.validate(self.data)

    def test_nested_unknown_fields_rejected(self):
        self.data["publication"]["approved"] = True
        with self.assertRaises(narradock.ManifestError):
            narradock.validate(self.data)

    def test_unsupported_version_rejected(self):
        self.data["schema_version"] = "9.0"
        with self.assertRaises(narradock.ManifestError):
            narradock.validate(self.data)

    def test_unsupported_source_rejected(self):
        self.data["source"]["kind"] = "remote_url"
        with self.assertRaises(narradock.ManifestError):
            narradock.validate(self.data)

    def test_bad_language_rejected(self):
        self.data["language"] = "not a language"
        with self.assertRaises(narradock.ManifestError):
            narradock.validate(self.data)

    def test_duplicate_keys_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.json"
            path.write_text('{"project_id":"one","project_id":"two"}', encoding="utf-8")
            with self.assertRaises(narradock.ManifestError):
                narradock.load_manifest(path)

    def test_invalid_encoding_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.json"
            path.write_bytes(bytes([255]))
            with self.assertRaises(narradock.ManifestError):
                narradock.load_manifest(path)

    def test_large_json_integer_has_safe_api_error(self):
        original_limit = sys.get_int_max_str_digits()
        try:
            sys.set_int_max_str_digits(4300)
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "synthetic-private-marker.json"
                path.write_text('{"schema_version":' + '1' * 5000 + '}', encoding="utf-8")
                with self.assertRaises(narradock.ManifestError) as caught:
                    narradock.load_manifest(path)
                self.assertEqual("Manifest could not be read as valid UTF-8 JSON",
                                 str(caught.exception))
        finally:
            sys.set_int_max_str_digits(original_limit)

    def test_large_json_integer_has_safe_cli_error(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "synthetic-private-marker.json"
            path.write_text('{"schema_version":' + '1' * 5000 + '}', encoding="utf-8")
            for command in ("validate", "plan"):
                with self.subTest(command=command):
                    result = subprocess.run(
                        [sys.executable, "-B", "-X", "int_max_str_digits=4300",
                         str(ROOT / "narradock.py"), command, str(path)],
                        cwd=temp, capture_output=True, check=False)
                    self.assertEqual(2, result.returncode)
                    self.assertEqual(b"", result.stdout)
                    self.assertEqual(
                        b"Invalid manifest: Manifest could not be read as valid UTF-8 JSON",
                        result.stderr.strip())
                    self.assertNotIn(b"Traceback", result.stderr)
                    self.assertNotIn(b"synthetic-private-marker", result.stderr)

    def test_specific_manifest_errors_are_preserved(self):
        cases = (
            (b'{"project_id":"one","project_id":"two"}', "Duplicate JSON key"),
            (b" " * (narradock.MAX_BYTES + 1), "Manifest exceeds size limit"),
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.json"
            for raw, message in cases:
                with self.subTest(message=message):
                    path.write_bytes(raw)
                    with self.assertRaises(narradock.ManifestError) as caught:
                        narradock.load_manifest(path)
                    self.assertEqual(message, str(caught.exception))

    def test_large_input_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.json"
            path.write_bytes(b" " * (narradock.MAX_BYTES + 1))
            with self.assertRaises(narradock.ManifestError):
                narradock.load_manifest(path)

    def test_cli_validate(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = narradock.main(["validate", str(ROOT / "examples/audio-only.json")])
        self.assertEqual(0, code)
        self.assertEqual("structure_only", json.loads(output.getvalue())["scope"])

    def test_cli_missing_file_does_not_echo_path(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "absent.json"
            with contextlib.redirect_stderr(io.StringIO()) as error:
                code = narradock.main(["plan", str(path)])
        self.assertEqual(2, code)
        self.assertNotIn(str(path), error.getvalue())


if __name__ == "__main__":
    unittest.main()
