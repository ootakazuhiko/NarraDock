"""Candidate measurements use only freshly generated, temporary synthetic WAVs."""
from contextlib import contextmanager
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import wave

import narradock_assets as assets
import narradock_audio as audio
import narradock_candidates as candidates


def chunk(kind, payload):
    return kind + struct.pack("<I", len(payload)) + payload + b"\0" * (len(payload) % 2)


def riff(*chunks):
    body = b"WAVE" + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def fmt(channels=1, rate=8000, tag=1, bits=16, align=None, byte_rate=None):
    align = channels * 2 if align is None else align
    byte_rate = rate * align if byte_rate is None else byte_rate
    return chunk(b"fmt ", struct.pack("<HHIIHH", tag, channels, rate, byte_rate, align, bits))


def pcm(*samples):
    return chunk(b"data", struct.pack("<" + "h" * len(samples), *samples))


class AudioTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.asset = self.root / "synthetic.wav"
        self.project = "sample-project"
        self.select(riff(fmt(), pcm(0, -32768, 32767, -20, 20, 0)))

    def select(self, data, duration=None):
        self.data = data
        self.asset.write_bytes(data)
        declaration = {"asset_id": "sample-audio", "size_bytes": len(data),
                       "sha256": hashlib.sha256(data).hexdigest()}
        self.registry = {"schema_version": assets.SCHEMA_VERSION, "project_id": self.project,
                         "assets": [{**declaration, "path": self.asset.name}]}
        self.candidate = {"schema_version": candidates.SCHEMA_VERSION,
            "project_id": self.project, "content_id": "sample-content", "audio": declaration,
            "metadata": {"title": "Neutral synthetic waveform", "language": "en", "credits": []}}
        if duration is not None:
            self.candidate["schema_version"] = candidates.TRANSCRIPT_SCHEMA_VERSION
            self.candidate["audio"]["duration_ms"] = duration
            self.candidate["transcript"] = {"fingerprint": "a" * 64}
        self.reselect()

    def reselect(self):
        self.revision = candidates.candidate_fingerprint(self.candidate, project_id=self.project)

    def measure(self, **kwargs):
        arguments = {"project_id": self.project, "expected_fingerprint": self.revision,
                     "registry": self.registry, "project_root": self.root}
        arguments.update(kwargs)
        return audio.measure_candidate_wav(self.candidate, **arguments)

    def reject(self, data):
        self.select(data)
        with self.assertRaisesRegex(audio.AudioMeasurementError,
                                    "^Candidate PCM WAV could not be measured$"):
            self.measure()

    def test_mono_measurements_and_receipt_boundaries(self):
        result = self.measure()
        self.assertEqual({"format": "signed-16-le", "channels": 1, "sample_rate_hz": 8000,
            "frame_count": 6, "sample_peak_abs": [32768], "full_scale_sample_count": [2],
            "zero_frame_count": 2}, result["pcm"])
        self.assertEqual({"milliseconds_numerator": 6000, "milliseconds_denominator": 8000,
            "rounded_ms": 1, "rounding": "nearest_ms_half_up", "declared_ms": None,
            "matches_declared": None}, result["duration"])
        self.assertEqual(self.revision, result["candidate_fingerprint"])
        self.assertEqual(self.candidate["audio"], result["audio"])
        self.assertEqual(self.project, result["project_id"])
        self.assertEqual("sample-content", result["content_id"])
        self.assertEqual(audio.SCHEMA_VERSION, result["schema_version"])
        self.assertEqual("candidate_pcm_wav_measurements_only", result["scope"])
        self.assertIs(True, result["measured"])
        self.assertIs(True, result["bytes_verified"])
        self.assertEqual([], result["findings"])
        for flag in ("rights_verified", "media_qa_passed", "human_reviewed", "packaged",
                     "transcript_alignment_verified", "external_transfer", "publication"):
            self.assertIs(False, result[flag])
        self.assertEqual([self.asset], list(self.root.iterdir()))
        self.assertEqual(self.data, self.asset.read_bytes())
        for private in (str(self.root), self.asset.name, self.candidate["metadata"]["title"]):
            self.assertNotIn(private, json.dumps(result))

    def test_stereo_counts_frames_and_channels_independently(self):
        self.select(riff(fmt(2), pcm(0, 0, 0, -32768, 32767, 100, -30, 0)))
        result = self.measure()["pcm"]
        self.assertEqual(4, result["frame_count"])
        self.assertEqual([32767, 32768], result["sample_peak_abs"])
        self.assertEqual([1, 1], result["full_scale_sample_count"])
        self.assertEqual(1, result["zero_frame_count"])

    def test_digital_zero_is_measured_without_qa_approval(self):
        self.select(riff(fmt(2), pcm(*([0] * 16))))
        result = self.measure()
        self.assertEqual(8, result["pcm"]["zero_frame_count"])
        self.assertEqual([0, 0], result["pcm"]["sample_peak_abs"])
        self.assertIs(False, result["media_qa_passed"])

    def test_duration_rounding_and_declared_match(self):
        for frames, rounded in ((3, 0), (4, 1), (11, 1), (12, 2), (8000, 1000)):
            with self.subTest(frames=frames):
                self.select(riff(fmt(), pcm(*([1] * frames))), duration=max(1, rounded))
                result = self.measure()
                self.assertEqual(frames * 1000, result["duration"]["milliseconds_numerator"])
                self.assertEqual(rounded, result["duration"]["rounded_ms"])
                self.assertIs(rounded != 0, result["duration"]["matches_declared"])
                self.assertEqual(["duration_mismatch"] if rounded == 0 else [], result["findings"])

    def test_duration_mismatch_is_an_observation_not_an_exception(self):
        self.select(riff(fmt(), pcm(*([1] * 8))), duration=6000)
        result = self.measure()
        self.assertEqual(1, result["duration"]["rounded_ms"])
        self.assertEqual(6000, result["duration"]["declared_ms"])
        self.assertIs(False, result["duration"]["matches_declared"])
        self.assertEqual(["duration_mismatch"], result["findings"])

    def test_standard_library_generated_wav_and_sample_rates(self):
        for channels in (1, 2):
            for rate in (8000, 44100, 48000, 192000):
                with self.subTest(channels=channels, rate=rate):
                    output = io.BytesIO()
                    with wave.open(output, "wb") as writer:
                        writer.setparams((channels, 2, rate, 0, "NONE", "not compressed"))
                        writer.writeframes(struct.pack("<h", 123) * (channels * 441))
                    self.select(output.getvalue())
                    result = self.measure()
                    self.assertEqual(441, result["pcm"]["frame_count"])
                    self.assertEqual(rate, result["duration"]["milliseconds_denominator"])
                    self.assertEqual([123] * channels, result["pcm"]["sample_peak_abs"])

    def test_odd_metadata_before_and_after_data_across_every_read_boundary(self):
        data = riff(chunk(b"JUNK", b"abc"), fmt(2), chunk(b"LIST", b"INFOx"),
                    pcm(0, -32768, 32767, 0, 0, 0), chunk(b"JUNK", b""),
                    chunk(b"LIST", b"INFO"), chunk(b"JUNK", b"z"))
        self.select(data)
        expected = self.measure()
        for read_size in range(1, len(data) + 1):
            with self.subTest(read_size=read_size), patch.object(assets, "CHUNK_BYTES", read_size):
                self.assertEqual(expected, self.measure())
        self.assertNotIn("INFO", json.dumps(expected))

    def test_large_payload_crosses_default_read_blocks(self):
        self.select(riff(fmt(2), pcm(*([0, 1] * 40000))))
        result = self.measure()["pcm"]
        self.assertEqual(40000, result["frame_count"])
        self.assertEqual([0, 1], result["sample_peak_abs"])
        self.assertEqual(0, result["zero_frame_count"])

    def test_stale_revision_and_invalid_candidate_fail_before_io(self):
        changes = [lambda c: c["metadata"].update(title="Changed title"),
                   lambda c: c.update(project_id="another-project"),
                   lambda c: c["audio"].update(sha256="b" * 64),
                   lambda c: c.update(extra=True)]
        original = copy.deepcopy(self.candidate)
        for change in changes:
            with self.subTest(change=change), patch.object(audio, "copy_verified_asset") as consume:
                self.candidate = copy.deepcopy(original)
                change(self.candidate)
                with self.assertRaises(audio.AudioMeasurementError):
                    self.measure()
                consume.assert_not_called()

    def test_transcript_and_duration_revision_changes_fail_before_io(self):
        self.select(self.data, duration=1)
        original = copy.deepcopy(self.candidate)
        for field in ("duration", "transcript"):
            self.candidate = copy.deepcopy(original)
            if field == "duration":
                self.candidate["audio"]["duration_ms"] = 2
            else:
                self.candidate["transcript"]["fingerprint"] = "b" * 64
            with patch.object(audio, "copy_verified_asset") as consume:
                with self.assertRaises(audio.AudioMeasurementError):
                    self.measure()
                consume.assert_not_called()

    def test_size_limits_fail_before_io(self):
        for size in (0, 45, audio.MAX_WAV_BYTES + 1):
            self.candidate["audio"]["size_bytes"] = size
            self.reselect()
            with self.subTest(size=size), patch.object(audio, "copy_verified_asset") as consume:
                with self.assertRaises(audio.AudioMeasurementError):
                    self.measure()
                consume.assert_not_called()

    def test_selected_size_is_enforced_even_if_registry_declares_more(self):
        self.candidate["audio"]["size_bytes"] -= 2
        self.reselect()
        with self.assertRaises(audio.AudioMeasurementError):
            self.measure()

    def test_registry_and_candidate_digests_must_both_match(self):
        for which in ("registry", "candidate"):
            self.select(self.data)
            if which == "registry":
                self.registry["assets"][0]["sha256"] = "b" * 64
            else:
                self.candidate["audio"]["sha256"] = "b" * 64
                self.reselect()
            with self.subTest(which=which), self.assertRaises(audio.AudioMeasurementError):
                self.measure()

    def test_cross_project_registry_and_untrusted_path_are_rejected(self):
        self.registry["project_id"] = "another-project"
        with self.assertRaises(audio.AudioMeasurementError):
            self.measure()
        self.registry["project_id"] = self.project
        self.registry["assets"][0]["path"] = "../synthetic.wav"
        with self.assertRaises(audio.AudioMeasurementError):
            self.measure()

    def test_snapshot_survives_caller_changes_during_read(self):
        expected = self.measure()
        consume = audio.copy_verified_asset
        def mutate(*args, **kwargs):
            self.candidate["metadata"]["title"] = "Changed after selection"
            self.candidate["audio"]["sha256"] = "b" * 64
            self.candidate["content_id"] = "changed-content"
            return consume(*args, **kwargs)
        with patch.object(audio, "copy_verified_asset", side_effect=mutate):
            self.assertEqual(expected, self.measure())

    def test_final_source_guard_failure_never_returns_measurements(self):
        original = assets._asset_fd
        @contextmanager
        def fail_at_exit(*args, **kwargs):
            with original(*args, **kwargs) as fd:
                yield fd
                raise assets.AssetError("Synthetic final guard failure")
        with patch.object(assets, "_asset_fd", fail_at_exit), \
                patch.object(audio._PcmWav, "finish") as finish:
            with self.assertRaises(audio.AudioMeasurementError):
                self.measure()
            finish.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "POSIX concurrent mutation case")
    def test_detected_source_change_after_last_read_rejects_measurements(self):
        original = audio._PcmWav.write
        def mutate(parser, data):
            count = original(parser, data)
            stat = self.asset.stat()
            os.utime(self.asset, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000000))
            return count
        with patch.object(audio._PcmWav, "write", mutate):
            with self.assertRaises(audio.AudioMeasurementError):
                self.measure()

    def test_rejects_non_riff_and_inconsistent_envelopes(self):
        for data in (b"RF64" + self.data[4:], b"RIFX" + self.data[4:],
                     self.data[:8] + b"AVI " + self.data[12:],
                     self.data + b"extra", self.data[:-1],
                     self.data[:4] + struct.pack("<I", 0xffffffff) + self.data[8:]):
            with self.subTest(data=data[:12]):
                self.reject(data)

    def test_rejects_unsupported_format_fields(self):
        variants = ({"tag": 3}, {"tag": 0xfffe}, {"channels": 0}, {"channels": 3},
                    {"rate": 7999}, {"rate": 192001}, {"bits": 8}, {"bits": 24},
                    {"align": 1}, {"byte_rate": 1})
        for kwargs in variants:
            with self.subTest(kwargs=kwargs):
                self.reject(riff(fmt(**kwargs), pcm(0, 1, 2, 3)))
        self.reject(riff(chunk(b"fmt ", fmt()[8:] + b"\0\0"), pcm(1, 2)))

    def test_rejects_missing_duplicate_and_misordered_chunks(self):
        for chunks in ((fmt(), fmt(), pcm(1)), (pcm(1), fmt()),
                       (fmt(), pcm(1), pcm(2)), (fmt(), chunk(b"JUNK", b"x" * 20)),
                       (chunk(b"JUNK", b"x" * 40),), (fmt(), pcm())):
            with self.subTest(chunks=[c[:4] for c in chunks]):
                self.reject(riff(*chunks))

    def test_rejects_incomplete_frames(self):
        self.reject(riff(fmt(), chunk(b"data", b"\0")))
        self.reject(riff(fmt(2), pcm(1, 2, 3)))

    def test_rejects_unknown_chunks_and_list_subtypes(self):
        for extra in (chunk(b"abcd", b""), chunk(b"fact", b"\0" * 4),
                      chunk(b"LIST", b"wavl"), chunk(b"LIST", b"INF")):
            with self.subTest(extra=extra):
                self.reject(riff(fmt(), pcm(1), extra))

    def test_rejects_chunk_overruns_and_partial_trailing_headers(self):
        for size in (1, 100, 0xffffffff):
            self.reject(riff(fmt(), pcm(1), b"JUNK" + struct.pack("<I", size)))
        for count in range(1, 8):
            self.reject(riff(fmt(), pcm(1), b"JUNK\0\0\0"[:count]))

    def test_requires_odd_chunk_padding_but_ignores_pad_value(self):
        good = riff(fmt(), pcm(1), chunk(b"JUNK", b"x"))
        self.select(good[:-1] + b"z")
        self.assertEqual(1, self.measure()["pcm"]["frame_count"])
        self.reject(riff(fmt(), pcm(1), b"JUNK\x01\0\0\0x"))

    def test_metadata_aggregate_limit_and_exact_boundary(self):
        limit = audio.MAX_METADATA_BYTES
        self.select(riff(chunk(b"JUNK", b"x" * (limit - 4)), fmt(), pcm(1),
                         chunk(b"LIST", b"INFO")))
        self.assertEqual(1, self.measure()["pcm"]["frame_count"])
        self.reject(riff(chunk(b"JUNK", b"x" * (limit - 4)), fmt(), pcm(1),
                         chunk(b"LIST", b"INFOx")))

    def test_chunk_count_limit_and_exact_boundary(self):
        self.select(riff(fmt(), *([chunk(b"JUNK", b"")] * (audio.MAX_CHUNKS - 2)), pcm(1)))
        self.assertEqual(1, self.measure()["pcm"]["frame_count"])
        self.reject(riff(fmt(), *([chunk(b"JUNK", b"")] * (audio.MAX_CHUNKS - 1)), pcm(1)))

    def test_truncated_streams_do_not_produce_results(self):
        data = riff(fmt(2), pcm(0, 1, 2, 3), chunk(b"LIST", b"INFOhello"))
        for end in range(46, len(data)):
            self.reject(data[:end])

    def test_incomplete_parser_is_rejected_after_verified_bytes(self):
        # The asset hashes correctly, but its outer envelope ends inside a header.
        self.reject(riff(fmt(), pcm(0, 1), b"LI"))


if __name__ == "__main__":
    unittest.main()
