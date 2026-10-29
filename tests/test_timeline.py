"""Chapter clocks use generated PCM fixtures; no real media or providers."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import narradock_assets as assets
import narradock_audio as audio
import narradock_candidates as candidates
import narradock_timeline as timelines
import narradock_transcript as transcripts


def canonical(document):
    return json.dumps(document, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def waveform(rate, frames, channels):
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, rate,
                                rate * channels * 2, channels * 2, 16)
    data = struct.pack("<h", 200) * frames * channels
    body = b"WAVE" + fmt + b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", len(body)) + body


class TimelineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = "sample-project"
        self.asset = self.root / "synthetic.wav"
        self.select()

    def select(self, rate=8000, frames=48, channels=1):
        self.wav = waveform(rate, frames, channels)
        self.asset.write_bytes(self.wav)
        ref = {"asset_id": "sample-audio", "sha256": hashlib.sha256(self.wav).hexdigest()}
        duration = (2 * frames * 1000 + rate) // (2 * rate)
        self.registry = {"schema_version": assets.SCHEMA_VERSION, "project_id": self.project,
            "assets": [{**ref, "size_bytes": len(self.wav), "path": self.asset.name}]}
        self.transcript = {"schema_version": transcripts.SCHEMA_VERSION, "project_id": self.project,
            "content_id": "sample-content", "language": "en", "audio": {**ref, "duration_ms": duration},
            "cues": [{"id": "first", "start_ms": 0, "end_ms": duration, "text": "Neutral cue."}]}
        self.candidate = {"schema_version": candidates.TRANSCRIPT_SCHEMA_VERSION,
            "project_id": self.project, "content_id": "sample-content",
            "audio": {**ref, "size_bytes": len(self.wav), "duration_ms": duration},
            "metadata": {"title": "Neutral candidate", "language": "en", "credits": []},
            "transcript": {"fingerprint": transcripts.fingerprint(self.transcript)}}
        self.candidate_revision = candidates.candidate_fingerprint(self.candidate, project_id=self.project)
        self.timeline = {"schema_version": timelines.SCHEMA_VERSION, "project_id": self.project,
            "content_id": "sample-content", "language": "en",
            "candidate_fingerprint": self.candidate_revision,
            "transcript_fingerprint": self.candidate["transcript"]["fingerprint"],
            "clock": {"sample_rate_hz": rate, "frame_count": frames},
            "chapters": [{"id": "opening", "title": "Opening", "start_frame": 0, "end_frame": frames}]}
        self.reselect()

    def reselect(self):
        self.revision = timelines.timeline_fingerprint(self.timeline, project_id=self.project)

    def verify(self, **kwargs):
        args = {"project_id": self.project, "expected_fingerprint": self.revision,
            "candidate": self.candidate, "expected_candidate_fingerprint": self.candidate_revision,
            "transcript": self.transcript, "registry": self.registry, "project_root": self.root}
        args.update(kwargs)
        return timelines.verify_timeline(self.timeline, **args)

    def reject(self, action):
        with self.assertRaisesRegex(timelines.TimelineError, "^Media timeline could not be validated$"):
            action()

    def reject_before_io(self, **kwargs):
        with patch.object(timelines, "measure_candidate_wav") as measure:
            self.reject(lambda: self.verify(**kwargs))
            measure.assert_not_called()

    def test_verifies_once_without_writing_or_claiming_alignment(self):
        before = copy.deepcopy((self.timeline, self.candidate, self.transcript, self.registry))
        with patch.object(audio, "copy_verified_asset", wraps=audio.copy_verified_asset) as read:
            result = self.verify()
        read.assert_called_once()
        self.assertEqual(before, (self.timeline, self.candidate, self.transcript, self.registry))
        self.assertEqual(self.wav, self.asset.read_bytes())
        self.assertEqual([self.asset], list(self.root.iterdir()))
        self.assertEqual(timelines.RECEIPT_SCHEMA_VERSION, result["schema_version"])
        self.assertEqual("candidate_pcm_chapter_timeline_only", result["scope"])
        self.assertTrue(result["bytes_verified"] and result["clock_verified"])
        self.assertEqual(self.revision, result["timeline_fingerprint"])
        self.assertEqual(self.candidate_revision, result["candidate_fingerprint"])
        self.assertEqual(self.timeline["transcript_fingerprint"], result["transcript_fingerprint"])
        self.assertEqual(self.timeline["clock"], result["clock"])
        self.assertEqual([{**self.timeline["chapters"][0], "start_ms": 0, "end_ms": 6}], result["chapters"])
        self.assertEqual("absolute_frame_nearest_ms_half_up", result["rounding"])
        self.assertEqual(self.candidate["audio"]["sha256"], result["measurements"]["audio"]["sha256"])
        for flag in ("rights_verified", "media_qa_passed", "human_reviewed", "packaged",
                     "transcript_alignment_verified", "chapter_alignment_verified", "external_transfer", "publication"):
            self.assertIs(False, result[flag])
        for private in (str(self.root), self.asset.name, self.candidate["metadata"]["title"]):
            self.assertNotIn(private, json.dumps(result))

    def test_absolute_rounding_does_not_accumulate_at_44100_hz(self):
        self.select(rate=44100, frames=4410)
        self.timeline["chapters"] = [{"id": f"chapter-{i}", "title": "Short interval",
            "start_frame": i * 21, "end_frame": (i + 1) * 21} for i in range(210)]
        self.reselect()
        chapters = self.verify()["chapters"]
        self.assertEqual(0, chapters[0]["end_ms"])
        self.assertEqual(100, chapters[-1]["end_ms"])
        self.assertEqual(100, sum(c["end_ms"] - c["start_ms"] for c in chapters))
        for left, right in zip(chapters, chapters[1:]):
            self.assertEqual(left["end_ms"], right["start_ms"])
            self.assertEqual(left["end_frame"], right["start_frame"])

    def test_half_up_one_frame_gaps_and_terminal_boundary(self):
        self.timeline["chapters"] = [
            {"id": "a", "title": "First", "start_frame": 3, "end_frame": 4},
            {"id": "b", "title": "Adjacent", "start_frame": 4, "end_frame": 5},
            {"id": "c", "title": "After a gap", "start_frame": 47, "end_frame": 48}]
        self.reselect()
        chapters = self.verify()["chapters"]
        self.assertEqual([(0, 1), (1, 1), (6, 6)], [(c["start_ms"], c["end_ms"]) for c in chapters])
        self.assertEqual(self.timeline["chapters"], [{k: c[k] for k in ("id", "title", "start_frame", "end_frame")} for c in chapters])

    def test_stereo_clock_counts_frames_not_channel_samples(self):
        self.select(channels=2)
        result = self.verify()
        self.assertEqual(2, result["measurements"]["pcm"]["channels"])
        self.assertEqual(48, result["clock"]["frame_count"])
        self.assertEqual(6, result["chapters"][0]["end_ms"])

    def test_existing_rounded_transcript_endpoint_is_not_remapped(self):
        for frames in (43, 45):
            self.select(rate=44100, frames=frames)
            before = copy.deepcopy(self.transcript)
            result = self.verify()
            self.assertEqual(1, result["chapters"][0]["end_ms"])
            self.assertEqual({"sample_rate_hz": 44100, "frame_count": frames}, result["clock"])
            self.assertEqual(before, self.transcript)

    def test_stale_timeline_or_independent_candidate_selection_rejected(self):
        for kwargs in ({"expected_fingerprint": "a" * 64}, {"expected_fingerprint": True},
                       {"expected_candidate_fingerprint": "a" * 64},
                       {"expected_candidate_fingerprint": None}):
            self.reject_before_io(**kwargs)
        self.timeline["chapters"][0]["title"] = "Changed title"
        self.reject_before_io()
        self.reselect()
        self.assertTrue(self.verify()["clock_verified"])

    def test_candidate_metadata_change_invalidates_old_timeline(self):
        self.candidate["metadata"]["title"] = "Revised candidate"
        self.candidate_revision = candidates.candidate_fingerprint(self.candidate, project_id=self.project)
        self.reject_before_io()

    def test_transcript_content_and_scope_changes_fail_before_io(self):
        for key, value in (("content_id", "other-content"), ("language", "ja"), ("project_id", "other-project")):
            changed = copy.deepcopy(self.transcript)
            changed[key] = value
            self.reject_before_io(transcript=changed)
        changed = copy.deepcopy(self.transcript)
        changed["cues"][0]["text"] = "Revised cue."
        self.reject_before_io(transcript=changed)
        changed["audio"]["sha256"] = "a" * 64
        self.reject_before_io(transcript=changed)

    def test_timeline_binding_fields_must_match_selected_inputs(self):
        original = copy.deepcopy(self.timeline)
        for key, value in (("content_id", "other"), ("language", "ja"),
                           ("candidate_fingerprint", "a" * 64), ("transcript_fingerprint", "b" * 64)):
            self.timeline = copy.deepcopy(original)
            self.timeline[key] = value
            self.reselect()
            self.reject_before_io()
        self.timeline = original
        self.reject_before_io(project_id="other-project")

    def test_legacy_candidate_without_transcript_rejected_before_io(self):
        self.candidate["schema_version"] = candidates.SCHEMA_VERSION
        del self.candidate["audio"]["duration_ms"], self.candidate["transcript"]
        self.candidate_revision = candidates.candidate_fingerprint(self.candidate, project_id=self.project)
        self.timeline["candidate_fingerprint"] = self.candidate_revision
        self.reselect()
        self.reject_before_io()

    def test_exact_clock_mismatch_even_when_rounded_duration_matches(self):
        self.timeline["clock"]["frame_count"] = 49
        self.reselect()
        self.reject(self.verify)
        self.timeline["clock"] = {"sample_rate_hz": 8001, "frame_count": 48}
        self.reselect()
        self.reject(self.verify)

    def test_declared_duration_mismatch_rejected_after_measurement(self):
        self.transcript["audio"]["duration_ms"] = 7
        self.candidate["audio"]["duration_ms"] = 7
        revision = transcripts.fingerprint(self.transcript)
        self.candidate["transcript"]["fingerprint"] = revision
        self.candidate_revision = candidates.candidate_fingerprint(self.candidate, project_id=self.project)
        self.timeline.update(candidate_fingerprint=self.candidate_revision, transcript_fingerprint=revision)
        self.reselect()
        self.reject(self.verify)

    def test_changed_missing_unsupported_or_cross_project_asset_rejected(self):
        self.asset.write_bytes(self.wav[:-2] + b"\0\0")
        self.reject(self.verify)
        self.asset.unlink()
        self.reject(self.verify)
        self.asset.write_bytes(self.wav)
        changed = copy.deepcopy(self.registry)
        changed["project_id"] = "other-project"
        self.reject(lambda: self.verify(registry=changed))
        unsupported = self.wav[:20] + struct.pack("<H", 3) + self.wav[22:]
        self.asset.write_bytes(unsupported)
        digest = hashlib.sha256(unsupported).hexdigest()
        self.registry["assets"][0]["sha256"] = digest
        self.candidate["audio"]["sha256"] = digest
        self.transcript["audio"]["sha256"] = digest
        revision = transcripts.fingerprint(self.transcript)
        self.candidate["transcript"]["fingerprint"] = revision
        self.candidate_revision = candidates.candidate_fingerprint(self.candidate, project_id=self.project)
        self.timeline.update(candidate_fingerprint=self.candidate_revision, transcript_fingerprint=revision)
        self.reselect()
        self.reject(self.verify)

    def test_late_verification_failure_never_returns_success(self):
        def fail_after_consuming(registry, **kwargs):
            kwargs["destination"].write(self.wav)
            raise assets.AssetError("Changed input")
        with patch.object(audio, "copy_verified_asset", side_effect=fail_after_consuming):
            self.reject(self.verify)
        self.assertEqual(self.wav, self.asset.read_bytes())

    def test_input_mutation_after_snapshot_does_not_change_selected_result(self):
        measure = timelines.measure_candidate_wav
        original_clock = copy.deepcopy(self.timeline["clock"])
        def change_inputs(*args, **kwargs):
            self.timeline["chapters"][0]["title"] = "Later title"
            self.timeline["clock"]["frame_count"] = 999
            self.candidate["metadata"]["title"] = "Later candidate"
            self.transcript["cues"][0]["text"] = "Later cue."
            return measure(*args, **kwargs)
        with patch.object(timelines, "measure_candidate_wav", side_effect=change_inputs):
            result = self.verify()
        self.assertEqual(original_clock, result["clock"])
        self.assertEqual("Opening", result["chapters"][0]["title"])

    def test_snapshots_and_results_do_not_alias_caller_objects(self):
        snapshot = timelines.snapshot_timeline(self.timeline, project_id=self.project)
        result = self.verify()
        snapshot["clock"]["frame_count"] = 999
        snapshot["chapters"].clear()
        result["clock"]["frame_count"] = 1000
        result["chapters"][0]["title"] = "Edited result"
        self.assertEqual(48, self.timeline["clock"]["frame_count"])
        self.assertEqual("Opening", self.timeline["chapters"][0]["title"])

    def test_canonical_identity_ignores_json_format_but_binds_all_fields(self):
        loaded = timelines.load_timeline(json.dumps(self.timeline, indent=2).encode(), project_id=self.project)
        self.assertEqual(self.timeline, loaded)
        self.assertEqual(hashlib.sha256(canonical(self.timeline)).hexdigest(), self.revision)
        self.assertEqual(self.revision, timelines.timeline_fingerprint(loaded, project_id=self.project))
        for key, value in (("language", "ja"), ("content_id", "other"), ("candidate_fingerprint", "a" * 64)):
            changed = copy.deepcopy(loaded)
            changed[key] = value
            self.assertNotEqual(self.revision, timelines.timeline_fingerprint(changed, project_id=self.project))
        for key, value in (("title", "Other"), ("id", "other"), ("start_frame", 1), ("end_frame", 47)):
            changed = copy.deepcopy(loaded)
            changed["chapters"][0][key] = value
            self.assertNotEqual(self.revision, timelines.timeline_fingerprint(changed, project_id=self.project))

    def test_schema_fields_types_ids_and_timing_are_strict(self):
        cases = [None, [], {**self.timeline, "tracks": []}, {**self.timeline, "schema_version": "media-timeline-9"}]
        for key, value in (("language", "e"), ("language", "x" * 21), ("project_id", "../escape"),
                           ("content_id", "A"), ("candidate_fingerprint", "A" * 64),
                           ("transcript_fingerprint", 1), ("chapters", []), ("chapters", {})):
            cases.append({**self.timeline, key: value})
        for key, value in (("sample_rate_hz", True), ("sample_rate_hz", 7999), ("sample_rate_hz", 192001),
                           ("frame_count", 0), ("frame_count", 48.0), ("frame_count", 10 ** 100)):
            cases.append({**self.timeline, "clock": {**self.timeline["clock"], key: value}})
        chapter = self.timeline["chapters"][0]
        for key, value in (("start_frame", -1), ("start_frame", True), ("end_frame", 49),
                           ("end_frame", 0), ("end_frame", "48"), ("id", "a" * 65), ("id", "A"),
                           ("title", " "), ("title", " title"), ("title", "title\n"),
                           ("title", "x\u2028y"), ("title", "x\ud800"), ("title", "x\ufeff"),
                           ("title", "x" * 201), ("title", "x\x00y")):
            cases.append({**self.timeline, "chapters": [{**chapter, key: value}]})
        cases.append({**self.timeline, "chapters": [{**chapter, "cue_id": "first"}]})
        for document in cases:
            with self.subTest(document_type=type(document).__name__):
                self.reject(lambda: timelines.snapshot_timeline(document, project_id=self.project))

    def test_chapter_overlap_order_and_duplicate_ids_rejected(self):
        chapter = self.timeline["chapters"][0]
        for chapters in ([chapter, chapter],
                         [{**chapter, "end_frame": 30}, {**chapter, "id": "b", "start_frame": 29}],
                         [{**chapter, "start_frame": 20}, {**chapter, "id": "b", "end_frame": 10}]):
            self.reject(lambda: timelines.snapshot_timeline({**self.timeline, "chapters": chapters}, project_id=self.project))

    def test_exact_24_hour_and_rate_boundaries_without_allocating_media(self):
        for rate in (8000, 44100, 192000):
            count = rate * 86400
            changed = copy.deepcopy(self.timeline)
            changed["clock"] = {"sample_rate_hz": rate, "frame_count": count}
            changed["chapters"][0].update(start_frame=count - 1, end_frame=count)
            self.assertEqual(count, timelines.snapshot_timeline(changed, project_id=self.project)["clock"]["frame_count"])
            changed["clock"]["frame_count"] += 1
            self.reject(lambda: timelines.snapshot_timeline(changed, project_id=self.project))

    def test_count_and_title_boundaries(self):
        self.timeline["clock"]["frame_count"] = 1001
        self.timeline["chapters"] = [{"id": f"chapter-{i}", "title": "a", "start_frame": i, "end_frame": i + 1}
                                     for i in range(1000)]
        self.assertEqual(1000, len(timelines.snapshot_timeline(self.timeline, project_id=self.project)["chapters"]))
        self.timeline["chapters"].append({"id": "extra", "title": "a", "start_frame": 1000, "end_frame": 1001})
        self.reject(lambda: timelines.snapshot_timeline(self.timeline, project_id=self.project))
        self.select()
        self.timeline["chapters"][0]["title"] = "\U0001f600" * 200
        self.assertEqual(self.timeline, timelines.snapshot_timeline(self.timeline, project_id=self.project))

    def test_raw_and_canonical_byte_limits(self):
        raw = canonical(self.timeline)
        padded = raw + b" " * (timelines.MAX_BYTES - len(raw))
        self.assertEqual(self.timeline, timelines.load_timeline(padded, project_id=self.project))
        self.reject(lambda: timelines.load_timeline(padded + b" ", project_id=self.project))
        self.timeline["clock"]["frame_count"] = 1000
        self.timeline["chapters"] = [{"id": f"chapter-{i}", "title": "\U0001f600" * 200,
            "start_frame": i, "end_frame": i + 1} for i in range(1000)]
        self.reject(lambda: timelines.snapshot_timeline(self.timeline, project_id=self.project))
        self.select()
        with patch.object(timelines, "MAX_BYTES", len(raw)):
            self.assertEqual(self.timeline, timelines.snapshot_timeline(self.timeline, project_id=self.project))
        with patch.object(timelines, "MAX_BYTES", len(raw) - 1):
            self.reject(lambda: timelines.snapshot_timeline(self.timeline, project_id=self.project))
        result_size = len(canonical(self.verify()))
        with patch.object(timelines, "MAX_RESULT_BYTES", result_size):
            self.verify()
        with patch.object(timelines, "MAX_RESULT_BYTES", result_size - 1):
            self.reject(self.verify)

    def test_json_duplicates_encoding_constants_and_depth_rejected(self):
        raw = canonical(self.timeline)
        variants = [b"", b"[]", b"null", b"{", b"\xff", b"\xef\xbb\xbf" + raw,
            raw + b"{}", raw.decode(), bytearray(raw), b"[" * 1500 + b"]" * 1500,
            raw.replace(b'"frame_count":48', b'"frame_count":NaN'),
            raw.replace(b'"frame_count":48', b'"frame_count":Infinity'),
            raw.replace(b'"frame_count":48', b'"frame_count":48,"frame_count":48'),
            raw.replace(b'"title":"Opening"', b'"title":"Opening","title":"Opening"'),
            raw.replace(b'"schema_version":', b'"schema_version":"media-timeline-0.1","schema_version":')]
        for data in variants:
            self.reject(lambda: timelines.load_timeline(data, project_id=self.project))

    def test_custom_timeline_primitives_are_rejected_without_hooks(self):
        class HostileString(str):
            def __hash__(self):
                raise AssertionError("custom hash invoked")
            def __eq__(self, other):
                raise AssertionError("custom equality invoked")
        class HostileDict(dict):
            def __getitem__(self, key):
                raise AssertionError("custom access invoked")
        class HostileList(list):
            def __len__(self):
                raise AssertionError("custom length invoked")
        for document in (HostileDict(self.timeline), {**self.timeline, "project_id": HostileString(self.project)},
                         {**self.timeline, "chapters": HostileList(self.timeline["chapters"])},
                         {**self.timeline, "clock": HostileDict(self.timeline["clock"])}):
            self.reject(lambda: timelines.snapshot_timeline(document, project_id=self.project))
        class Key(str):
            pass
        changed = {Key(k): v for k, v in self.timeline.items()}
        self.reject(lambda: timelines.snapshot_timeline(changed, project_id=self.project))

    def test_literal_titles_preserved_without_interpretation_or_normalization(self):
        title = '<b>Section</b> & e\u0301 / \u00e9 / \u7ae0'
        self.timeline["chapters"][0]["title"] = title
        self.reselect()
        self.assertEqual(title, self.verify()["chapters"][0]["title"])
        before = self.revision
        self.timeline["chapters"][0]["title"] = title.replace("e\u0301", "\u00e9")
        self.reselect()
        self.assertNotEqual(before, self.revision)

    def test_example_is_structural_only(self):
        data = (Path(__file__).resolve().parents[1] / "examples" / "media-timeline.json").read_bytes()
        result = timelines.load_timeline(data, project_id="sample-project")
        self.assertEqual(44100, result["clock"]["sample_rate_hz"])
        self.assertEqual(2, len(result["chapters"]))


if __name__ == "__main__":
    unittest.main()
