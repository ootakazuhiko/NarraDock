"""Offline package tests with synthetic bytes and explicitly fictitious decisions."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import narradock_assets as assets
import narradock_candidates as candidates
import narradock_packages as packages
import narradock_transcript as transcripts

REPO = Path(__file__).resolve().parents[1]


class PackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.parent = Path(temporary.name).resolve()
        self.root, self.output = self.parent / "project", self.parent / "output"
        (self.root / "inputs").mkdir(parents=True)
        self.output.mkdir()
        self.data = b"Neutral asset example.\n"
        self.asset = self.root / "inputs" / "example.dat"
        self.asset.write_bytes(self.data)
        self.candidate = json.loads((REPO / "examples/candidate-record.json").read_text())
        self.registry = json.loads((REPO / "examples/asset-registry.json").read_text())
        self.project = "sample-project"
        self.fingerprint = candidates.candidate_fingerprint(self.candidate, project_id=self.project)
        self.decisions = {"schema_version": packages.DECISIONS_VERSION,
            "project_id": self.project, "candidate_fingerprint": self.fingerprint,
            "decision_id": "synthetic-decision",
            "rights": {"status": "approved", "evidence_id": "synthetic-rights"},
            "technical_qa": {"status": "approved", "evidence_id": "synthetic-qa"},
            "human_review": {"status": "approved", "evidence_id": "synthetic-review",
                             "reviewer_id": "synthetic-reviewer"},
            "local_packaging": {"status": "approved", "authority_id": "synthetic-authority"}}

    def build(self, **kwargs):
        arguments = {"project_id": self.project, "expected_fingerprint": self.fingerprint,
            "decisions": self.decisions, "registry": self.registry, "project_root": self.root,
            "output_directory": self.output}
        arguments.update(kwargs)
        return packages.create_audio_package(self.candidate, **arguments)

    def final_path(self, directory=None):
        return (self.output if directory is None else directory) / (self.fingerprint + ".zip")

    def transcript_document(self):
        return {"schema_version": transcripts.SCHEMA_VERSION, "project_id": self.project,
            "content_id": self.candidate["content_id"], "language": "en",
            "audio": {"asset_id": "sample-input", "sha256": hashlib.sha256(self.data).hexdigest(),
                      "duration_ms": 6000},
            "cues": [{"id": "first-cue", "start_ms": 500, "end_ms": 1500,
                      "text": '<b>A & B</b> --> &lt; "quote"'},
                     {"id": "second-cue", "start_ms": 2500, "end_ms": 5500,
                      "text": "Neutral second cue."}]}

    def select_transcript(self, sidecar):
        self.candidate["schema_version"] = candidates.TRANSCRIPT_SCHEMA_VERSION
        self.candidate["audio"]["duration_ms"] = 6000
        self.candidate["transcript"] = {"fingerprint": transcripts.fingerprint(sidecar)}
        self.fingerprint = candidates.candidate_fingerprint(self.candidate, project_id=self.project)
        self.decisions["candidate_fingerprint"] = self.fingerprint

    def reject_without_io(self, **kwargs):
        with patch("narradock_packages.copy_verified_asset") as consume, \
                patch("narradock_packages._output_directory") as output:
            with self.assertRaises(packages.PackageError):
                self.build(**kwargs)
            consume.assert_not_called()
            output.assert_not_called()

    def test_package_contents_receipt_and_privacy(self):
        result = self.build()
        raw = self.final_path().read_bytes()
        self.assertEqual({"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
                         result["package"])
        self.assertEqual(self.fingerprint, result["candidate_fingerprint"])
        self.assertIs(True, result["packaged"])
        self.assertIs(True, result["decisions_bound"])
        for key in ("rights_verified", "media_qa_passed", "external_transfer", "publication"):
            self.assertIs(False, result[key])
        with zipfile.ZipFile(self.final_path()) as archive:
            self.assertEqual(["audio.bin", "candidate.json", "manifest.json"], archive.namelist())
            self.assertEqual(self.data, archive.read("audio.bin"))
            self.assertEqual(self.candidate, json.loads(archive.read("candidate.json")))
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(packages.SCHEMA_VERSION, manifest["schema_version"])
            self.assertEqual(self.fingerprint, manifest["candidate_fingerprint"])
            for name in ("audio.bin", "candidate.json"):
                content = archive.read(name)
                self.assertEqual({"sha256": hashlib.sha256(content).hexdigest(),
                                  "size_bytes": len(content)}, manifest["files"][name])
            for entry in archive.infolist():
                self.assertEqual((1980, 1, 1, 0, 0, 0), entry.date_time)
                self.assertEqual(zipfile.ZIP_STORED, entry.compress_type)
                self.assertEqual(3, entry.create_system)
                self.assertEqual(0o100600 << 16, entry.external_attr)
        for private in (str(self.root), str(self.output), "inputs/example.dat", "synthetic-rights",
                        "synthetic-reviewer", "synthetic-authority", result["decisions_fingerprint"]):
            self.assertNotIn(private.encode(), raw)
        self.assertNotIn(self.candidate["metadata"]["title"], json.dumps(result))
        self.assertEqual([self.final_path()], list(self.output.iterdir()))
        self.assertEqual(self.data, self.asset.read_bytes())

    def test_audio_only_version_one_compatibility_golden(self):
        # Captured from the merged audio-only implementation before this extension.
        result = self.build()
        self.assertEqual("5e874d274267a05520e292c13b691d5ecec9e99a04cf7e4cad70ff3737be7b96",
                         result["candidate_fingerprint"])
        self.assertEqual({"size_bytes": 1111,
                          "sha256": "db4fbb05801a2aa8a2ca6a84bb741cd5dcb3f5a57917b4325ee7c65c62c16843"},
                         result["package"])

    def test_transcript_package_contents_binding_and_escaping(self):
        sidecar = self.transcript_document()
        self.select_transcript(sidecar)
        result = self.build(transcript=sidecar)
        raw = self.final_path().read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), result["package"]["sha256"])
        with zipfile.ZipFile(self.final_path()) as archive:
            self.assertEqual(["audio.bin", "candidate.json", "transcript.json", "transcript.vtt",
                              "manifest.json"], archive.namelist())
            self.assertEqual(self.data, archive.read("audio.bin"))
            transcript_json = archive.read("transcript.json")
            self.assertEqual(sidecar, json.loads(transcript_json))
            self.assertEqual(self.candidate["transcript"]["fingerprint"],
                             hashlib.sha256(transcript_json).hexdigest())
            vtt = archive.read("transcript.vtt").decode("utf-8")
            self.assertEqual(transcripts.to_webvtt(sidecar), vtt)
            self.assertIn("00:00:00.500 --> 00:00:01.500", vtt)
            self.assertIn('&lt;b&gt;A &amp; B&lt;/b&gt; --&gt; &amp;lt; "quote"', vtt)
            self.assertNotIn("<b>", vtt)
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(packages.TRANSCRIPT_SCHEMA_VERSION, manifest["schema_version"])
            self.assertEqual(set(archive.namelist()) - {"manifest.json"}, set(manifest["files"]))
            for name, record in manifest["files"].items():
                payload = archive.read(name)
                self.assertEqual({"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}, record)
        for private in ("synthetic-rights", "synthetic-reviewer", str(self.root)):
            self.assertNotIn(private.encode(), raw)
        for flag in ("rights_verified", "media_qa_passed", "external_transfer", "publication"):
            self.assertIs(False, result[flag])
        self.assertNotIn(sidecar["cues"][0]["text"], json.dumps(result))

    def test_transcript_argument_is_version_specific_before_io(self):
        self.reject_without_io(transcript=self.transcript_document())
        self.reject_without_io(transcript={})
        self.select_transcript(self.transcript_document())
        self.reject_without_io()
        self.reject_without_io(transcript={})

    def test_each_transcript_revision_change_rejects_stale_selection(self):
        original = self.transcript_document()
        self.select_transcript(original)
        changes = [("text", "Edited cue"), ("id", "changed-cue"),
                   ("start_ms", 600), ("end_ms", 1600)]
        for key, value in changes:
            changed = copy.deepcopy(original)
            changed["cues"][0][key] = value
            self.reject_without_io(transcript=changed)
        changed = copy.deepcopy(original)
        changed["language"] = "ja"
        self.reject_without_io(transcript=changed)

    def test_new_transcript_identity_cannot_reuse_old_decisions(self):
        sidecar = self.transcript_document()
        self.select_transcript(sidecar)
        old_decisions = copy.deepcopy(self.decisions)
        old_fingerprint = self.fingerprint
        sidecar["cues"][0]["text"] = "Reviewed new revision"
        self.select_transcript(sidecar)
        self.assertNotEqual(old_fingerprint, self.fingerprint)
        self.reject_without_io(transcript=sidecar, expected_fingerprint=old_fingerprint)
        self.reject_without_io(transcript=sidecar, decisions=old_decisions)

    def test_transcript_reference_binding_is_independent_of_its_fingerprint(self):
        for path, key, value in (((), "project_id", "other-project"),
                                 ((), "content_id", "other-content"),
                                 (("audio",), "asset_id", "other-input"),
                                 (("audio",), "sha256", "a" * 64),
                                 (("audio",), "duration_ms", 6001),
                                 ((), "language", "ja")):
            sidecar = self.transcript_document()
            target = sidecar
            for part in path:
                target = target[part]
            target[key] = value
            # Select and approve the altered fingerprint, but retain independently
            # supplied candidate scope/audio/duration/language; binding must fail.
            self.select_transcript(sidecar)
            self.reject_without_io(transcript=sidecar)

    def test_transcript_snapshot_survives_caller_mutation_during_copy(self):
        sidecar = self.transcript_document()
        selected = copy.deepcopy(sidecar)
        self.select_transcript(sidecar)
        consume = packages.copy_verified_asset
        def mutate(*args, **kwargs):
            sidecar["cues"][0]["text"] = "Unselected replacement"
            sidecar["audio"]["duration_ms"] = 1
            sidecar["cues"].clear()
            self.candidate["transcript"]["fingerprint"] = "0" * 64
            return consume(*args, **kwargs)
        with patch("narradock_packages.copy_verified_asset", side_effect=mutate):
            self.build(transcript=sidecar)
        with zipfile.ZipFile(self.final_path()) as archive:
            self.assertEqual(selected, json.loads(archive.read("transcript.json")))
            self.assertEqual(transcripts.to_webvtt(selected).encode(), archive.read("transcript.vtt"))

    def test_invalid_transcript_text_is_rejected_before_io(self):
        sidecar = self.transcript_document()
        self.select_transcript(sidecar)
        for text in ("cue\n\nSTYLE\n::cue { color: red; }", "text\u2028injection", "text\x00"):
            sidecar["cues"][0]["text"] = text
            self.reject_without_io(transcript=sidecar)

    def test_oversized_transcript_fails_before_legacy_encoding_and_io(self):
        sidecar = self.transcript_document()
        self.select_transcript(sidecar)
        sidecar["cues"] = [{"id": f"cue-{index}", "start_ms": index * 2, "end_ms": index * 2 + 1,
                            "text": "z" * transcripts.MAX_TEXT} for index in range(600)]
        # Structurally valid direct input exceeds the serialized package limit.
        transcripts.validate(sidecar)
        with patch("narradock_packages.transcripts.fingerprint") as fingerprint, \
                patch("narradock_packages.transcripts.to_webvtt") as render:
            self.reject_without_io(transcript=sidecar)
            fingerprint.assert_not_called()
            render.assert_not_called()

    def test_webvtt_output_limit_precedes_io(self):
        sidecar = self.transcript_document()
        self.select_transcript(sidecar)
        encoded = transcripts.to_webvtt(sidecar).encode()
        with patch.object(packages, "MAX_WEBVTT_BYTES", len(encoded) - 1):
            self.reject_without_io(transcript=sidecar)
        with patch.object(packages, "MAX_WEBVTT_BYTES", len(encoded)):
            self.build(transcript=sidecar)

    def test_transcript_package_is_reproducible(self):
        sidecar = self.transcript_document()
        self.select_transcript(sidecar)
        first = self.build(transcript=sidecar)
        other = self.parent / "repeat-output"
        other.mkdir()
        second = self.build(transcript=sidecar, output_directory=other)
        self.assertEqual(first["package"], second["package"])

    def test_transcript_package_copy_failure_and_collision_cleanup(self):
        sidecar = self.transcript_document()
        self.select_transcript(sidecar)
        self.asset.write_bytes(b"x" * len(self.data))
        with self.assertRaises(packages.PackageError):
            self.build(transcript=sidecar)
        self.assertEqual([], list(self.output.iterdir()))
        self.asset.write_bytes(self.data)
        self.build(transcript=sidecar)
        completed = self.final_path().read_bytes()
        with self.assertRaises(packages.PackageError):
            self.build(transcript=sidecar)
        self.assertEqual(completed, self.final_path().read_bytes())
        self.assertEqual([self.final_path()], list(self.output.iterdir()))

    def test_reproducible_package_and_distinct_private_decisions(self):
        first = self.build()
        another = self.parent / "second-output"
        another.mkdir()
        self.decisions["decision_id"] = "another-synthetic-decision"
        second = self.build(output_directory=another)
        self.assertEqual(first["package"], second["package"])
        self.assertNotEqual(first["decisions_fingerprint"], second["decisions_fingerprint"])
        self.assertEqual(self.final_path().read_bytes(), self.final_path(another).read_bytes())

    def test_candidate_revision_and_project_gate_precede_io(self):
        for expected in (None, True, "", "0" * 64):
            self.reject_without_io(expected_fingerprint=expected)
        self.reject_without_io(project_id="other-project")
        self.candidate["metadata"]["title"] = "Changed title"
        self.reject_without_io()
        new = candidates.candidate_fingerprint(self.candidate, project_id=self.project)
        self.reject_without_io(expected_fingerprint=new)

    def test_decision_binding_and_schema_are_exact(self):
        for key, value in (("schema_version", "other"), ("project_id", "other-project"),
                           ("candidate_fingerprint", "0" * 64), ("decision_id", "../unsafe")):
            record = copy.deepcopy(self.decisions)
            record[key] = value
            self.reject_without_io(decisions=record)
        for key in [*self.decisions, "extra"]:
            record = copy.deepcopy(self.decisions)
            if key == "extra": record[key] = True
            else: del record[key]
            self.reject_without_io(decisions=record)
        for record in (None, [], "approved", True):
            self.reject_without_io(decisions=record)

    def test_each_required_decision_and_reference_is_explicit(self):
        for name in ("rights", "technical_qa", "human_review", "local_packaging"):
            for status in (None, True, "pending", "rejected", "Approved"):
                record = copy.deepcopy(self.decisions)
                record[name]["status"] = status
                self.reject_without_io(decisions=record)
            for key in [*self.decisions[name], "extra"]:
                record = copy.deepcopy(self.decisions)
                if key == "extra": record[name][key] = True
                else: del record[name][key]
                self.reject_without_io(decisions=record)
            for key in set(self.decisions[name]) - {"status"}:
                for value in (None, True, [], "", "a" * 65, "MixedCase", "a\nb"):
                    record = copy.deepcopy(self.decisions)
                    record[name][key] = value
                    self.reject_without_io(decisions=record)

    def test_snapshot_prevents_caller_mutation(self):
        original_candidate, original_decisions = copy.deepcopy(self.candidate), copy.deepcopy(self.decisions)
        consume = packages.copy_verified_asset
        def mutate(*args, **kwargs):
            self.candidate["metadata"]["title"] = "Unselected title"
            self.candidate["metadata"]["credits"].append("Unselected credit")
            self.candidate["audio"]["sha256"] = "0" * 64
            self.decisions["rights"]["status"] = "rejected"
            return consume(*args, **kwargs)
        with patch("narradock_packages.copy_verified_asset", side_effect=mutate):
            result = self.build()
        with zipfile.ZipFile(self.final_path()) as archive:
            self.assertEqual(original_candidate, json.loads(archive.read("candidate.json")))
        canonical = json.dumps(original_decisions, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), result["decisions_fingerprint"])

    def test_public_candidate_snapshot_is_independent(self):
        snapshot = candidates.snapshot_candidate(self.candidate, project_id=self.project)
        snapshot["metadata"]["credits"].clear()
        snapshot["audio"]["size_bytes"] = 0
        self.assertTrue(self.candidate["metadata"]["credits"])
        self.assertEqual(len(self.data), self.candidate["audio"]["size_bytes"])

    def test_empty_and_multichunk_payloads(self):
        for index, data in enumerate((b"", b"z" * (assets.CHUNK_BYTES * 2 + 13))):
            self.asset.write_bytes(data)
            declaration = {"size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            self.registry["assets"][0].update(declaration)
            self.candidate["audio"].update(declaration)
            self.fingerprint = candidates.candidate_fingerprint(self.candidate, project_id=self.project)
            self.decisions["candidate_fingerprint"] = self.fingerprint
            self.build()
            with zipfile.ZipFile(self.final_path()) as archive:
                self.assertEqual(data, archive.read("audio.bin"))

    def test_stale_bytes_registry_and_candidate_leave_no_output(self):
        self.asset.write_bytes(b"x" * len(self.data))
        with self.assertRaises(packages.PackageError):
            self.build()
        self.assertEqual([], list(self.output.iterdir()))
        self.registry["assets"][0]["sha256"] = hashlib.sha256(self.asset.read_bytes()).hexdigest()
        with self.assertRaisesRegex(packages.PackageError, "declaration mismatch"):
            self.build()
        self.assertEqual([], list(self.output.iterdir()))
        self.registry["project_id"] = "other-project"
        with self.assertRaises(packages.PackageError):
            self.build()
        self.assertEqual([], list(self.output.iterdir()))

    def test_source_final_guard_failure_does_not_promote(self):
        consume = packages.copy_verified_asset
        def fail(*args, **kwargs):
            consume(*args, **kwargs)
            raise assets.AssetError("Synthetic final guard failure")
        with patch("narradock_packages.copy_verified_asset", side_effect=fail), \
                patch("narradock_packages.os.link") as link:
            with self.assertRaises(packages.PackageError):
                self.build()
            link.assert_not_called()
        self.assertEqual([], list(self.output.iterdir()))

    def test_existing_file_and_directory_are_not_replaced(self):
        final = self.final_path()
        final.write_bytes(b"Keep existing bytes")
        with self.assertRaises(packages.PackageError):
            self.build()
        self.assertEqual(b"Keep existing bytes", final.read_bytes())
        final.unlink()
        final.mkdir()
        with self.assertRaises(packages.PackageError):
            self.build()
        self.assertTrue(final.is_dir())
        self.assertEqual([final], list(self.output.iterdir()))

    def test_destination_created_during_build_is_preserved(self):
        link = os.link
        def collide(source, destination):
            Path(destination).write_bytes(b"Another completed output")
            link(source, destination)
        with patch("narradock_packages.os.link", side_effect=collide):
            with self.assertRaises(packages.PackageError):
                self.build()
        self.assertEqual(b"Another completed output", self.final_path().read_bytes())
        self.assertEqual([self.final_path()], list(self.output.iterdir()))

    def test_final_name_appears_only_for_completed_archive(self):
        link = os.link
        def inspect(source, destination):
            self.assertFalse(Path(destination).exists())
            with zipfile.ZipFile(source) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(self.data, archive.read("audio.bin"))
            return link(source, destination)
        with patch("narradock_packages.os.link", side_effect=inspect):
            self.build()
        self.assertEqual(1, self.final_path().stat().st_nlink)

    def test_write_sync_and_promotion_failures_leave_no_output(self):
        for target in ("narradock_packages.zipfile.ZipFile.writestr",
                       "narradock_packages.os.fsync", "narradock_packages.os.link"):
            with self.subTest(target=target), patch(target, side_effect=OSError("private details")):
                with self.assertRaises(packages.PackageError) as error:
                    self.build()
                self.assertNotIn("private", str(error.exception))
            self.assertEqual([], list(self.output.iterdir()))

    def test_zip_close_failure_leaves_no_output(self):
        close = zipfile.ZipFile.close
        def fail(archive):
            was_open = archive.fp is not None
            close(archive)
            if was_open:
                raise OSError("Synthetic close failure")
        with patch("narradock_packages.zipfile.ZipFile.close", new=fail):
            with self.assertRaises(packages.PackageError):
                self.build()
        self.assertEqual([], list(self.output.iterdir()))

    def test_cleanup_failure_reports_uncertainty(self):
        unlink = Path.unlink
        failed = False
        def fail_once(path, *args, **kwargs):
            nonlocal failed
            if path.suffix == ".tmp" and not failed:
                failed = True
                raise OSError("Synthetic cleanup failure")
            return unlink(path, *args, **kwargs)
        with patch("narradock_packages.Path.unlink", new=fail_once):
            with self.assertRaises(packages.PackageError):
                self.build()
        self.assertEqual([], list(self.output.iterdir()))

    def test_cleanup_attempts_remaining_path_after_rollback_failure(self):
        unlink = Path.unlink
        stages = 0
        def fail(path, *args, **kwargs):
            nonlocal stages
            if path.suffix == ".tmp":
                stages += 1
                if stages > 1:
                    return unlink(path, *args, **kwargs)
            raise OSError("Synthetic cleanup failure")
        with patch("narradock_packages.Path.unlink", new=fail):
            with self.assertRaisesRegex(packages.PackageError, "could not be removed"):
                self.build()
        self.assertEqual(2, stages)
        self.assertEqual([self.final_path()], list(self.output.iterdir()))
        with zipfile.ZipFile(self.final_path()) as archive:
            self.assertIsNone(archive.testzip())

    def test_output_stream_failures_do_not_promote(self):
        fdopen = os.fdopen
        for operation in ("flush", "read", "close"):
            class Stream:
                def __init__(self, *args, **kwargs):
                    self.inner = fdopen(*args, **kwargs)
                def __getattr__(self, name):
                    return getattr(self.inner, name)
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    self.inner.close()
                    if operation == "close":
                        raise OSError("Synthetic close failure")
                def flush(self):
                    if operation == "flush":
                        raise OSError("Synthetic flush failure")
                    return self.inner.flush()
                def read(self, count):
                    if operation == "read":
                        raise OSError("Synthetic read failure")
                    return self.inner.read(count)
            with self.subTest(operation=operation), patch("narradock_packages.os.fdopen", new=Stream):
                with self.assertRaises(packages.PackageError):
                    self.build()
            self.assertEqual([], list(self.output.iterdir()))

    def test_fdopen_failure_closes_descriptor_and_removes_stage(self):
        descriptors = []
        def fail(descriptor, *args):
            descriptors.append(descriptor)
            raise OSError("Synthetic stream creation failure")
        with patch("narradock_packages.os.fdopen", side_effect=fail):
            with self.assertRaises(packages.PackageError):
                self.build()
        self.assertEqual([], list(self.output.iterdir()))
        with self.assertRaises(OSError):
            os.fstat(descriptors[0])

    def test_unicode_metadata_is_preserved(self):
        self.candidate["metadata"].update(title="静かな音声 e\u0301", credits=["作者例", "Sample credit"])
        self.fingerprint = candidates.candidate_fingerprint(self.candidate, project_id=self.project)
        self.decisions["candidate_fingerprint"] = self.fingerprint
        self.build()
        with zipfile.ZipFile(self.final_path()) as archive:
            raw = archive.read("candidate.json")
            self.assertIn("静かな音声 e\u0301".encode(), raw)
            self.assertEqual(self.candidate, json.loads(raw))

    def test_output_directory_requirements(self):
        for directory in (Path("relative"), self.root, self.root / "inputs",
                          self.output / "missing", self.output / ".." / "output"):
            with self.subTest(directory=directory), patch("narradock_packages.copy_verified_asset") as consume:
                with self.assertRaises(packages.PackageError):
                    self.build(output_directory=directory)
                consume.assert_not_called()
        self.assertEqual([], list(self.output.iterdir()))

    @unittest.skipUnless(os.name == "posix", "POSIX symlink creation")
    def test_output_alias_into_source_and_existing_symlink(self):
        alias = self.parent / "alias"
        alias.symlink_to(self.root / "inputs", target_is_directory=True)
        with self.assertRaises(packages.PackageError):
            self.build(output_directory=alias)
        target = self.parent / "untouched"
        target.write_bytes(b"Keep target")
        self.final_path().symlink_to(target)
        with self.assertRaises(packages.PackageError):
            self.build()
        self.assertTrue(self.final_path().is_symlink())
        self.assertEqual(b"Keep target", target.read_bytes())

    def test_no_receipt_is_a_reusable_byte_verification(self):
        self.build()
        self.asset.write_bytes(b"x" * len(self.data))
        another = self.parent / "another-output"
        another.mkdir()
        with self.assertRaises(packages.PackageError):
            self.build(output_directory=another)
        self.assertEqual([], list(another.iterdir()))


if __name__ == "__main__":
    unittest.main()
