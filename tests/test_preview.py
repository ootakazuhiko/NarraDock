"""Candidate previews use temporary synthetic media and never write output files."""
import base64
from contextlib import contextmanager
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
import narradock_player as player
import narradock_preview as previews
import narradock_transcript as transcripts
from test_player import Page


def wav_bytes(frames=48, extra=b""):
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 16000, 2, 16)
    data = b"data" + struct.pack("<I", frames * 2) + struct.pack("<h", 200) * frames
    body = b"WAVE" + fmt + data + extra
    return b"RIFF" + struct.pack("<I", len(body)) + body


class PreviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = "sample-project"
        self.asset = self.root / "synthetic.wav"
        self.wav = wav_bytes()
        self.asset.write_bytes(self.wav)
        reference = {"asset_id": "sample-audio", "sha256": hashlib.sha256(self.wav).hexdigest()}
        self.registry = {"schema_version": "asset-registry-0.1", "project_id": self.project,
            "assets": [{**reference, "size_bytes": len(self.wav), "path": "synthetic.wav"}]}
        self.transcript = {"schema_version": transcripts.SCHEMA_VERSION, "project_id": self.project,
            "content_id": "sample-content", "language": "en", "audio": {**reference, "duration_ms": 6},
            "cues": [{"id": "first", "start_ms": 0, "end_ms": 2, "text": "Neutral first cue."},
                     {"id": "last", "start_ms": 3, "end_ms": 6, "text": "Neutral last cue."}]}
        self.candidate = {"schema_version": candidates.TRANSCRIPT_SCHEMA_VERSION,
            "project_id": self.project, "content_id": "sample-content",
            "audio": {**reference, "size_bytes": len(self.wav), "duration_ms": 6},
            "metadata": {"title": "Neutral preview", "language": "en", "credits": ["Synthetic credit"]},
            "transcript": {"fingerprint": transcripts.fingerprint(self.transcript)}}
        self.reselect()

    def reselect(self, *, transcript=False):
        if transcript:
            self.candidate["transcript"]["fingerprint"] = transcripts.fingerprint(self.transcript)
        self.revision = candidates.candidate_fingerprint(self.candidate, project_id=self.project)

    def build(self, **kwargs):
        arguments = {"project_id": self.project, "expected_fingerprint": self.revision,
                     "transcript": self.transcript, "registry": self.registry, "project_root": self.root}
        arguments.update(kwargs)
        return previews.build_candidate_preview(self.candidate, **arguments)

    def reject_before_io(self, **kwargs):
        with patch.object(previews, "read_candidate_wav") as read, \
                patch.object(player, "_render_page") as render:
            with self.assertRaisesRegex(previews.PreviewError, "^Candidate audio preview could not be created$"):
                self.build(**kwargs)
            read.assert_not_called()
            render.assert_not_called()

    def test_preview_embeds_the_selected_verified_bytes_and_transcript(self):
        before_candidate, before_transcript = copy.deepcopy(self.candidate), copy.deepcopy(self.transcript)
        with patch.object(audio, "copy_verified_asset", wraps=audio.copy_verified_asset) as consume:
            output, receipt = self.build()
        consume.assert_called_once()
        self.assertIs(type(output), bytes)
        page = Page(output.decode("utf-8"))
        blocks = {attrs.get("id"): value for tag, attrs, value in page.blocks if tag == "script"}
        self.assertEqual(self.wav, base64.b64decode(blocks["audio-data"].split(",", 1)[1], validate=True))
        self.assertEqual(self.transcript, json.loads(blocks["transcript-data"]))
        self.assertEqual(before_candidate, self.candidate)
        self.assertEqual(before_transcript, self.transcript)
        self.assertEqual(self.wav, self.asset.read_bytes())
        self.assertEqual([self.asset], list(self.root.iterdir()))
        self.assertEqual(self.revision, receipt["candidate_fingerprint"])
        self.assertEqual(self.candidate["transcript"]["fingerprint"], receipt["transcript_fingerprint"])
        self.assertEqual({"size_bytes": len(output), "sha256": hashlib.sha256(output).hexdigest()}, receipt["html"])
        self.assertEqual(previews.SCHEMA_VERSION, receipt["schema_version"])
        self.assertEqual("candidate_local_preview_only", receipt["scope"])
        self.assertIs(True, receipt["preview_created"])
        self.assertIs(True, receipt["measurements"]["duration"]["matches_declared"])
        self.assertEqual(48, receipt["measurements"]["pcm"]["frame_count"])
        for key in ("rights_verified", "media_qa_passed", "human_reviewed", "packaged",
                    "transcript_alignment_verified", "external_transfer", "publication"):
            self.assertIs(False, receipt[key])
        self.assertIn(b"LOCAL PREVIEW", output)
        self.assertNotIn(b"PLAYER DEMO", output)
        for private in (str(self.root), self.asset.name):
            self.assertNotIn(private, output.decode("utf-8"))
            self.assertNotIn(private, json.dumps(receipt))
        for text in ("Neutral preview", "Synthetic credit", "Neutral first cue."):
            self.assertNotIn(text, json.dumps(receipt))

    def test_result_is_repeatable(self):
        self.assertEqual(self.build(), self.build())

    def test_old_candidate_schema_and_stale_fingerprints_fail_before_io(self):
        self.reject_before_io(expected_fingerprint="b" * 64)
        self.candidate["metadata"]["title"] = "Changed title"
        self.reject_before_io()
        self.candidate["schema_version"] = candidates.SCHEMA_VERSION
        del self.candidate["transcript"], self.candidate["audio"]["duration_ms"]
        self.reselect()
        self.reject_before_io()

    def test_every_sidecar_scope_and_revision_mismatch_fails_before_io(self):
        original = copy.deepcopy(self.transcript)
        changes = [("project_id", "another-project"), ("content_id", "another-content"),
                   ("language", "ja"), ("asset_id", "another-audio"), ("sha256", "b" * 64),
                   ("duration_ms", 7), ("text", "Changed text"), ("end_ms", 1)]
        for key, value in changes:
            self.transcript = copy.deepcopy(original)
            target = self.transcript["audio"] if key in {"asset_id", "sha256", "duration_ms"} else (
                self.transcript["cues"][0] if key in {"text", "end_ms"} else self.transcript)
            target[key] = value
            with self.subTest(key=key):
                self.reject_before_io()

    def test_refingerprinting_a_mismatched_binding_still_fails(self):
        self.transcript["audio"]["asset_id"] = "another-audio"
        self.reselect(transcript=True)
        self.reject_before_io()

    def test_missing_transcript_and_invalid_custom_types_fail_before_io(self):
        self.reject_before_io(transcript=None)
        self.reject_before_io(transcript={})
        class Custom(dict):
            def __deepcopy__(self, memo):
                raise AssertionError("Caller hook must not run")
        self.reject_before_io(transcript=Custom(self.transcript))
        self.candidate = Custom(self.candidate)
        self.reject_before_io()

    def test_audio_caps_fail_before_io(self):
        for size in (0, 45, audio.MAX_CAPTURE_BYTES + 1):
            self.candidate["audio"]["size_bytes"] = size
            self.reselect()
            self.reject_before_io()

    def test_cue_count_and_canonical_byte_limits_fail_before_io(self):
        self.candidate["audio"]["duration_ms"] = self.transcript["audio"]["duration_ms"] = 1001
        self.transcript["cues"] = [{"id": f"cue-{i}", "start_ms": i, "end_ms": i+1, "text": "x"}
                                   for i in range(1001)]
        self.reselect(transcript=True)
        self.reject_before_io()
        self.transcript["cues"] = self.transcript["cues"][:600]
        for cue in self.transcript["cues"]:
            cue["text"] = "x" * 4000
        self.reselect(transcript=True)
        self.reject_before_io()

    def test_escaped_text_and_payload_output_caps_fail_before_io(self):
        self.transcript["cues"][0]["text"] = "<" * 100
        self.reselect(transcript=True)
        escaped = len(player._json_for_html(self.transcript).encode("utf-8"))
        with patch.object(previews, "MAX_ESCAPED_TRANSCRIPT_BYTES", escaped - 1):
            self.reject_before_io()
        with patch.object(previews, "MAX_HTML_BYTES", escaped - 1):
            self.reject_before_io()
        with patch.object(previews, "MAX_ESCAPED_TRANSCRIPT_BYTES", escaped):
            self.assertIs(True, self.build()[1]["preview_created"])

    def test_final_utf8_output_cap_is_enforced(self):
        output, _ = self.build()
        with patch.object(previews, "MAX_HTML_BYTES", len(output)):
            self.assertEqual(output, self.build()[0])
        with patch.object(previews, "MAX_HTML_BYTES", len(output) - 1):
            with self.assertRaises(previews.PreviewError):
                self.build()

    def test_duration_mismatch_blocks_preview_but_remains_a_measurement_finding(self):
        self.transcript["audio"]["duration_ms"] = self.candidate["audio"]["duration_ms"] = 7
        self.reselect(transcript=True)
        with patch.object(player, "_render_page") as render:
            with self.assertRaises(previews.PreviewError):
                self.build()
            render.assert_not_called()
        _, measurement = audio.read_candidate_wav(self.candidate, project_id=self.project,
            expected_fingerprint=self.revision, registry=self.registry, project_root=self.root)
        self.assertEqual(["duration_mismatch"], measurement["findings"])

    def test_half_millisecond_rounding_is_retained_in_receipt(self):
        self.wav = wav_bytes(frames=44)  # 5.5 ms, half up to the declared 6 ms.
        self.asset.write_bytes(self.wav)
        digest = hashlib.sha256(self.wav).hexdigest()
        self.candidate["audio"].update(size_bytes=len(self.wav), sha256=digest)
        self.registry["assets"][0].update(size_bytes=len(self.wav), sha256=digest)
        self.transcript["audio"]["sha256"] = digest
        self.reselect(transcript=True)
        duration = self.build()[1]["measurements"]["duration"]
        self.assertEqual((44000, 8000, 6), (duration["milliseconds_numerator"],
            duration["milliseconds_denominator"], duration["rounded_ms"]))

    def test_source_and_registry_failures_never_render(self):
        for kind in ("registry-hash", "candidate-hash", "cross-project", "path"):
            old_candidate, old_registry, old_transcript = map(copy.deepcopy,
                (self.candidate, self.registry, self.transcript))
            if kind == "registry-hash": self.registry["assets"][0]["sha256"] = "b" * 64
            if kind == "candidate-hash":
                self.candidate["audio"]["sha256"] = self.transcript["audio"]["sha256"] = "b" * 64
                self.reselect(transcript=True)
            if kind == "cross-project": self.registry["project_id"] = "another-project"
            if kind == "path": self.registry["assets"][0]["path"] = "../synthetic.wav"
            with self.subTest(kind=kind), patch.object(player, "_render_page") as render:
                with self.assertRaises(previews.PreviewError): self.build()
                render.assert_not_called()
            self.candidate, self.registry, self.transcript = old_candidate, old_registry, old_transcript
            self.reselect()

    def test_final_source_guard_failure_never_renders(self):
        original = assets._asset_fd
        @contextmanager
        def fail_at_exit(*args, **kwargs):
            with original(*args, **kwargs) as fd:
                yield fd
                raise assets.AssetError("Synthetic final guard failure")
        with patch.object(assets, "_asset_fd", fail_at_exit), patch.object(player, "_render_page") as render:
            with self.assertRaises(previews.PreviewError): self.build()
            render.assert_not_called()

    def test_caller_mutation_cannot_change_frozen_rendered_inputs(self):
        expected = self.build()
        original = audio.copy_verified_asset
        def mutate(*args, **kwargs):
            self.candidate["metadata"]["title"] = "Changed title"
            self.candidate["audio"]["sha256"] = "b" * 64
            self.transcript["cues"][0]["text"] = "Changed cue"
            return original(*args, **kwargs)
        with patch.object(audio, "copy_verified_asset", side_effect=mutate):
            self.assertEqual(expected, self.build())

    def test_markup_metadata_and_cues_are_literal_and_language_is_explicit(self):
        literal = '</script><img src=x onerror="alert(1)">& <b>literal</b> 😀'
        self.candidate["metadata"].update(title=literal, credits=[literal])
        self.transcript["cues"][0]["text"] = literal
        self.reselect(transcript=True)
        output, _ = self.build()
        page = Page(output.decode("utf-8"))
        self.assertFalse(any(tag in {"img", "b"} for tag, _ in page.tags))
        self.assertEqual(4, sum(tag == "script" for tag, _ in page.tags))
        self.assertEqual("ja", next(attrs["lang"] for tag, attrs in page.tags if tag == "html"))
        self.assertEqual("en", next(attrs["lang"] for tag, attrs in page.tags if attrs.get("id") == "transcript"))
        payload = next(text for _, attrs, text in page.blocks if attrs.get("id") == "transcript-data")
        self.assertEqual(literal, json.loads(payload)["cues"][0]["text"])
        policy = next(attrs["content"] for _, attrs in page.tags if attrs.get("http-equiv") == "Content-Security-Policy")
        for tag, attrs, text in page.blocks:
            if tag == "style" or (tag == "script" and not attrs):
                self.assertIn(base64.b64encode(hashlib.sha256(text.encode()).digest()).decode(), policy)

    def test_opaque_wav_metadata_is_preserved_in_private_output(self):
        extra = b"LIST" + struct.pack("<I", 8) + b"INFOtest"
        self.wav = wav_bytes(extra=extra)
        self.asset.write_bytes(self.wav)
        digest = hashlib.sha256(self.wav).hexdigest()
        self.candidate["audio"].update(size_bytes=len(self.wav), sha256=digest)
        self.registry["assets"][0].update(size_bytes=len(self.wav), sha256=digest)
        self.transcript["audio"]["sha256"] = digest
        self.reselect(transcript=True)
        output, receipt = self.build()
        page = Page(output.decode())
        embedded = next(value for _, attrs, value in page.blocks if attrs.get("id") == "audio-data")
        self.assertEqual(self.wav, base64.b64decode(embedded.split(",", 1)[1]))
        self.assertNotIn("INFOtest", json.dumps(receipt))


if __name__ == "__main__":
    unittest.main()
