import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import narradock_candidates as candidates

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "narradock_candidates.py"


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name).resolve()
        self.root = self.parent / "project"
        (self.root / "inputs").mkdir(parents=True)
        self.data = b"Neutral asset example.\n"
        self.file = self.root / "inputs" / "example.dat"
        self.file.write_bytes(self.data)
        self.document = json.loads((REPO / "examples/candidate-record.json").read_text())
        self.registry = json.loads((REPO / "examples/asset-registry.json").read_text())
        self.registry_file = self.parent / "registry.json"
        self.registry_file.write_text(json.dumps(self.registry))
        self.project = "sample-project"

    def fingerprint(self, document=None):
        return candidates.candidate_fingerprint(self.document if document is None else document,
                                                project_id=self.project)

    def transcript_candidate(self):
        document = copy.deepcopy(self.document)
        document["schema_version"] = candidates.TRANSCRIPT_SCHEMA_VERSION
        document["audio"]["duration_ms"] = 6000
        document["transcript"] = {"fingerprint": "a" * 64}
        return document

    def test_transcript_candidate_load_and_byte_verification(self):
        document = self.transcript_candidate()
        self.assertEqual(document, self.load(json.dumps(document).encode()))
        result = self.verify(document)
        self.assertEqual(self.fingerprint(document), result["candidate_fingerprint"])
        self.assertEqual("candidate_asset_bytes_only", result["scope"])
        self.assertIs(False, result["media_qa_passed"])
        self.assertIs(False, result["packaged"])

    def test_version_specific_transcript_fields(self):
        version_two = self.transcript_candidate()
        rejected = []
        wrong_version = copy.deepcopy(version_two)
        wrong_version["schema_version"] = candidates.SCHEMA_VERSION
        rejected.append(wrong_version)
        missing_transcript = copy.deepcopy(version_two)
        del missing_transcript["transcript"]
        rejected.append(missing_transcript)
        missing_duration = copy.deepcopy(version_two)
        del missing_duration["audio"]["duration_ms"]
        rejected.append(missing_duration)
        for sidecar in (None, [], {}, {"fingerprint": "a" * 64, "extra": True},
                        {"fingerprint": "A" * 64}, {"fingerprint": True}):
            rejected.append(dict(version_two, transcript=sidecar))
        for document in rejected:
            with self.assertRaises(candidates.CandidateError):
                candidates.validate_candidate(document, project_id=self.project)

    def test_transcript_candidate_duration_limits(self):
        for duration in (0, -1, True, 1.0, "6000", None, candidates.MAX_DURATION_MS + 1):
            document = self.transcript_candidate()
            document["audio"]["duration_ms"] = duration
            with self.assertRaises(candidates.CandidateError):
                candidates.validate_candidate(document, project_id=self.project)
        for duration in (1, candidates.MAX_DURATION_MS):
            document = self.transcript_candidate()
            document["audio"]["duration_ms"] = duration
            candidates.validate_candidate(document, project_id=self.project)

    def test_transcript_identity_and_duration_change_candidate_revision(self):
        document = self.transcript_candidate()
        original = self.fingerprint(document)
        document["transcript"]["fingerprint"] = "b" * 64
        self.assertNotEqual(original, self.fingerprint(document))
        document = self.transcript_candidate()
        document["audio"]["duration_ms"] += 1
        self.assertNotEqual(original, self.fingerprint(document))
        snapshot = candidates.snapshot_candidate(document, project_id=self.project)
        snapshot["transcript"]["fingerprint"] = "c" * 64
        self.assertEqual("a" * 64, document["transcript"]["fingerprint"])

    def verify(self, document=None, **kwargs):
        document = self.document if document is None else document
        args = {"project_id": self.project, "expected_fingerprint": self.fingerprint(document),
                "registry": self.registry, "project_root": self.root}
        args.update(kwargs)
        return candidates.verify_candidate_asset(document, **args)

    def load(self, raw):
        return candidates.load_candidate(io.BytesIO(raw), project_id=self.project)

    def test_actual_bytes_match_candidate_without_authorizing_operations(self):
        result = self.verify()
        self.assertEqual("candidate_asset_bytes_only", result["scope"])
        self.assertIs(True, result["verified"])
        self.assertEqual(self.fingerprint(), result["candidate_fingerprint"])
        self.assertEqual(hashlib.sha256(self.data).hexdigest(), result["audio"]["sha256"])
        self.assertEqual(len(self.data), result["audio"]["size_bytes"])
        for field in ("rights_verified", "media_qa_passed", "human_reviewed", "packaged",
                      "external_transfer", "publication"):
            self.assertIs(False, result[field])
        encoded = json.dumps(result)
        self.assertNotIn(str(self.root), encoded)
        self.assertNotIn(self.document["metadata"]["title"], encoded)
        self.assertNotIn(self.document["metadata"]["credits"][0], encoded)
        self.assertEqual(self.data, self.file.read_bytes())
        self.assertEqual(["inputs"], sorted(p.name for p in self.root.iterdir()))

    def test_structure_and_fingerprint_do_not_read_assets(self):
        self.file.unlink()
        with patch("narradock_candidates.verify_asset") as verify:
            self.assertIsNone(candidates.validate_candidate(self.document, project_id=self.project))
            self.assertEqual(64, len(self.fingerprint()))
            verify.assert_not_called()

    def test_expected_revision_rejected_before_asset_io(self):
        for expected in (None, True, "", "a" * 63, "A" * 64, "0" * 64):
            with self.subTest(expected=expected), patch("narradock_candidates.verify_asset") as verify:
                with self.assertRaisesRegex(candidates.CandidateError, "fingerprint mismatch"):
                    self.verify(expected_fingerprint=expected)
                verify.assert_not_called()

    def test_expected_revision_is_required(self):
        with self.assertRaises(TypeError):
            candidates.verify_candidate_asset(self.document, project_id=self.project,
                registry=self.registry, project_root=self.root)

    def test_project_mismatch_rejected_before_asset_io(self):
        with patch("narradock_candidates.verify_asset") as verify:
            with self.assertRaisesRegex(candidates.CandidateError, "project mismatch"):
                self.verify(project_id="another-project")
            verify.assert_not_called()

    def test_each_declared_field_changes_revision(self):
        changes = [((), "project_id", "another-project"), ((), "content_id", "other-content"),
                   (("audio",), "asset_id", "other-input"), (("audio",), "sha256", "a" * 64),
                   (("audio",), "size_bytes", 24), (("metadata",), "title", "Another title"),
                   (("metadata",), "language", "ja"), (("metadata",), "credits", ["Another credit"])]
        original = self.fingerprint()
        for path, key, value in changes:
            document = copy.deepcopy(self.document)
            target = document
            for part in path: target = target[part]
            target[key] = value
            with self.subTest(key=key):
                changed = candidates.candidate_fingerprint(document, project_id=document["project_id"])
                self.assertNotEqual(original, changed)

    def test_object_key_order_and_json_layout_do_not_change_revision(self):
        def reverse(value):
            if isinstance(value, dict): return {key: reverse(value[key]) for key in reversed(value)}
            if isinstance(value, list): return [reverse(item) for item in value]
            return value
        raw = json.dumps(reverse(self.document), indent=4).encode()
        self.assertEqual(self.fingerprint(), self.fingerprint(self.load(raw)))

    def test_unicode_whitespace_and_credit_order_are_preserved(self):
        document = copy.deepcopy(self.document)
        for left, right in [("Café", "Cafe\u0301"), ("Title", " Title ")]:
            document["metadata"]["title"] = left
            first = self.fingerprint(document)
            document["metadata"]["title"] = right
            self.assertNotEqual(first, self.fingerprint(document))
        document["metadata"]["credits"] = ["First", "Second"]
        first = self.fingerprint(document)
        document["metadata"]["credits"].reverse()
        self.assertNotEqual(first, self.fingerprint(document))

    def test_fingerprint_has_independent_canonical_json_vector(self):
        document = copy.deepcopy(self.document)
        document["metadata"]["title"] = "中立の例"
        canonical = ('{"audio":{"asset_id":"sample-input","sha256":'
                     '"6ebac37f797e9aa5e7ee9e4492aa6daa407937b6a63bf0162235c627d6dcf503",'
                     '"size_bytes":23},"content_id":"sample-content","metadata":'
                     '{"credits":["Synthetic example bytes"],"language":"en","title":"中立の例"},'
                     '"project_id":"sample-project","schema_version":"audio-candidate-0.1"}')
        self.assertEqual(hashlib.sha256(canonical.encode("utf-8")).hexdigest(), self.fingerprint(document))

    def test_metadata_change_rejects_previous_selection(self):
        expected = self.fingerprint()
        self.document["metadata"]["title"] = "Revised title"
        with patch("narradock_candidates.verify_asset") as verify:
            with self.assertRaisesRegex(candidates.CandidateError, "fingerprint mismatch"):
                self.verify(expected_fingerprint=expected)
            verify.assert_not_called()

    def test_valid_registry_receipt_cannot_override_candidate_declaration(self):
        for key, value in [("sha256", "a" * 64), ("size_bytes", 22)]:
            document = copy.deepcopy(self.document)
            document["audio"][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(candidates.CandidateError, "declaration mismatch"):
                self.verify(document)

    def test_missing_asset_registry_project_mismatch_and_file_change_rejected(self):
        self.verify()
        self.file.write_bytes(b"x" * len(self.data))
        with self.assertRaises(candidates.CandidateError): self.verify()
        self.file.write_bytes(self.data)
        document = copy.deepcopy(self.document)
        document["audio"]["asset_id"] = "missing-input"
        with self.assertRaises(candidates.CandidateError): self.verify(document)
        registry = copy.deepcopy(self.registry)
        registry["project_id"] = "another-project"
        with self.assertRaises(candidates.CandidateError): self.verify(registry=registry)

    def test_same_asset_id_in_two_projects_cannot_reuse_verification(self):
        other = self.parent / "other-project"
        (other / "inputs").mkdir(parents=True)
        (other / "inputs" / "example.dat").write_bytes(b"x" * len(self.data))
        document = copy.deepcopy(self.document)
        document["project_id"] = "other-project"
        registry = copy.deepcopy(self.registry)
        registry["project_id"] = "other-project"
        self.verify()
        expected = candidates.candidate_fingerprint(document, project_id="other-project")
        with self.assertRaises(candidates.CandidateError):
            candidates.verify_candidate_asset(document, project_id="other-project",
                expected_fingerprint=expected, registry=registry, project_root=other)

    def test_verification_uses_one_snapshot_despite_caller_mutation(self):
        expected = self.fingerprint()
        original = candidates.verify_asset
        def verify(*args, **kwargs):
            self.document["content_id"] = "changed-content"
            self.document["audio"]["asset_id"] = "changed-input"
            self.document["metadata"]["credits"].append("Changed credit")
            return original(*args, **kwargs)
        with patch("narradock_candidates.verify_asset", side_effect=verify):
            result = self.verify(expected_fingerprint=expected)
        self.assertEqual(expected, result["candidate_fingerprint"])
        self.assertEqual("sample-content", result["content_id"])
        self.assertEqual("sample-input", result["audio"]["asset_id"])

    def test_unknown_missing_fields_and_bad_schema_rejected(self):
        for path in [(), ("audio",), ("metadata",)]:
            for operation in ("add", "remove"):
                document = copy.deepcopy(self.document)
                target = document
                for part in path: target = target[part]
                if operation == "add": target["unknown"] = "value"
                else: target.pop(next(iter(target)))
                with self.assertRaises(candidates.CandidateError): self.fingerprint(document)
        self.document["schema_version"] = "future"
        with self.assertRaises(candidates.CandidateError): self.fingerprint()

    def test_identifier_hash_size_and_language_limits(self):
        cases = [((), "content_id", ["", "UPPER", "a--b", "a" * 65, None]),
                 (("audio",), "size_bytes", [True, -1, 1.5, candidates.MAX_ASSET_BYTES + 1]),
                 (("audio",), "sha256", ["0" * 63, "A" * 64, None]),
                 (("metadata",), "language", ["", "EN", "en-us", "ja-JP-private", None])]
        for path, key, invalid in cases:
            for value in invalid:
                document = copy.deepcopy(self.document)
                target = document
                for part in path: target = target[part]
                target[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(candidates.CandidateError):
                    self.fingerprint(document)
        for size in (0, candidates.MAX_ASSET_BYTES):
            self.document["audio"]["size_bytes"] = size
            self.fingerprint()

    def test_text_controls_surrogates_and_limits(self):
        invalid = ["", " \t ", "a" * 201, "line\nbreak", "tab\tvalue", "nul\0value",
                   "format\u200bvalue", "surrogate\ud800", "line\u2028value", "para\u2029value"]
        for value in invalid:
            for key in ("title", "credits"):
                document = copy.deepcopy(self.document)
                document["metadata"][key] = value if key == "title" else [value]
                with self.subTest(key=key), self.assertRaises(candidates.CandidateError): self.fingerprint(document)
        self.document["metadata"]["title"] = "a" * 200
        self.fingerprint()

    def test_credit_count_type_and_duplicates(self):
        for value in (None, "credit", ["same", "same"], [str(i) for i in range(17)]):
            document = copy.deepcopy(self.document)
            document["metadata"]["credits"] = value
            with self.assertRaises(candidates.CandidateError): self.fingerprint(document)
        for value in ([], [str(i) for i in range(16)]):
            self.document["metadata"]["credits"] = value
            self.fingerprint()

    def test_loader_strict_json_and_utf8_failures(self):
        raw = json.dumps(self.document).encode()
        invalid = [b'{"project_id":"one","project_id":"two"}',
                   raw.replace(b'"title":', b'"title":"duplicate", "title":'),
                   b"{", b"\xff", b"\xef\xbb\xbf" + raw,
                   b'{"size":' + b"1" * 5000 + b"}", b"[" * 2000 + b"]" * 2000,
                   b'{"value":NaN}', b'{"value":Infinity}', b'{"value":-Infinity}']
        for data in invalid:
            with self.assertRaises(candidates.CandidateError): self.load(data)

    def test_stream_limit_exact_boundary_and_bounded_reads(self):
        raw = json.dumps(self.document).encode()
        raw += b" " * (candidates.MAX_CANDIDATE_BYTES - len(raw))
        self.assertEqual(self.fingerprint(), self.fingerprint(self.load(raw)))
        class Stream(io.BytesIO):
            def __init__(self, data): super().__init__(data); self.sizes = []
            def read(self, size): self.sizes.append(size); return super().read(size)
        source = Stream(raw + b" " * 10000)
        with self.assertRaisesRegex(candidates.CandidateError, "size limit"):
            candidates.load_candidate(source, project_id=self.project)
        self.assertEqual(candidates.MAX_CANDIDATE_BYTES + 1, source.tell())
        self.assertLessEqual(max(source.sizes), candidates.READ_CHUNK_BYTES)

    def test_stream_is_not_closed_and_short_reads_work(self):
        class ShortStream(io.BytesIO):
            def read(self, size): return super().read(min(3, size))
        source = ShortStream(json.dumps(self.document).encode())
        loaded = candidates.load_candidate(source, project_id=self.project)
        self.assertFalse(source.closed)
        self.assertEqual(self.fingerprint(), self.fingerprint(loaded))

    def test_stream_errors_and_nonbinary_input_are_sanitized(self):
        with patch.object(io.BytesIO(), "read", side_effect=OSError("private-marker")) as read:
            class BadStream:
                pass
            source = BadStream(); source.read = read
            with self.assertRaises(candidates.CandidateError) as caught:
                candidates.load_candidate(source, project_id=self.project)
        self.assertNotIn("private-marker", str(caught.exception))
        with self.assertRaises(candidates.CandidateError):
            candidates.load_candidate(io.StringIO("{}"), project_id=self.project)
        class OversizedStream:
            def read(self, size): return b"x" * (size + 1)
        with self.assertRaises(candidates.CandidateError):
            candidates.load_candidate(OversizedStream(), project_id=self.project)

    def test_asset_errors_do_not_expose_paths(self):
        with self.assertRaises(candidates.CandidateError) as caught:
            self.verify(project_root=self.parent / "private-path-marker")
        self.assertEqual("Candidate asset could not be verified", str(caught.exception))

    def cli(self, *args, data=None):
        return subprocess.run([sys.executable, "-B", str(CLI), *args],
                              input=json.dumps(self.document).encode() if data is None else data,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)

    def test_cli_structure_and_verification_scopes(self):
        validated = self.cli("validate", "--project-id", self.project)
        self.assertEqual(0, validated.returncode, validated.stderr)
        result = json.loads(validated.stdout)
        self.assertEqual("candidate_structure_only", result["scope"])
        self.assertIs(False, result["bytes_verified"])
        verified = self.cli("verify", "--project-id", self.project,
            "--expected-fingerprint", result["candidate_fingerprint"], "--registry",
            str(self.registry_file), "--project-root", str(self.root))
        self.assertEqual(0, verified.returncode, verified.stderr)
        self.assertEqual("candidate_asset_bytes_only", json.loads(verified.stdout)["scope"])

    def test_cli_rejects_stale_selection_before_registry_read(self):
        result = self.cli("verify", "--project-id", self.project, "--expected-fingerprint", "0" * 64,
                          "--registry", str(self.parent / "private-marker"), "--project-root", str(self.root))
        self.assertEqual(2, result.returncode)
        self.assertEqual(b"", result.stdout)
        self.assertEqual(b"Invalid candidate: Candidate fingerprint mismatch\n", result.stderr.replace(b"\r\n", b"\n"))

    def test_cli_invalid_input_has_no_traceback_or_metadata(self):
        for args, data in [(["unknown-private-marker"], b"{}"),
                           (["validate", "--project-id", self.project], b"{private-marker"),
                           (["verify", "--project-id", self.project], None),
                           (["validate", "--project-id", self.project, "--expected-fingerprint", "a" * 64], None),
                           (["verify", "--project-id", self.project, "--expected-fingerprint", self.fingerprint(),
                             "--registry", str(self.parent / "private-marker"), "--project-root", str(self.root)], None)]:
            result = self.cli(*args, data=data)
            self.assertEqual(2, result.returncode)
            self.assertEqual(b"", result.stdout)
            self.assertNotIn(b"private-marker", result.stderr)
            self.assertNotIn(b"Traceback", result.stderr)
            self.assertNotIn(str(self.parent).encode(), result.stderr)

    def test_cli_closed_pipe_returns_safe_error(self):
        read_fd, write_fd = os.pipe()
        os.close(read_fd)
        try:
            result = subprocess.run([sys.executable, "-E", "-B", str(CLI), "validate", "--project-id", self.project],
                input=json.dumps(self.document).encode(), stdout=write_fd, stderr=subprocess.PIPE, timeout=10)
        finally:
            os.close(write_fd)
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertEqual([b"Invalid candidate: Output could not be written"], result.stderr.splitlines())


if __name__ == "__main__":
    unittest.main()
