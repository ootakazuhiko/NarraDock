"""Offline generation tests; browser behavior has separate Node/browser checks."""
import base64
import copy
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

import narradock_audio as audio
import narradock_candidates as candidates
import narradock_player as player
import narradock_transcript as transcripts

REPO = Path(__file__).resolve().parents[1]


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.blocks = []
        self.current = None
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if tag in {"script", "style"}:
            self.current = [tag, attrs, ""]
            self.blocks.append(self.current)

    def handle_endtag(self, tag):
        if self.current and self.current[0] == tag:
            self.current = None

    def handle_data(self, data):
        if self.current:
            self.current[2] += data


class PlayerTests(unittest.TestCase):
    def test_fixture_has_actual_audio_digest_and_valid_transcript(self):
        transcript, wav = player.synthetic_fixture()
        transcripts.validate(transcript)
        self.assertEqual(hashlib.sha256(wav).hexdigest(), transcript["audio"]["sha256"])
        self.assertNotEqual("a" * 64, transcript["audio"]["sha256"])
        with wave.open(io.BytesIO(wav)) as reader:
            self.assertEqual((1, 2, 8000, 192000),
                (reader.getnchannels(), reader.getsampwidth(), reader.getframerate(), reader.getnframes()))
        self.assertEqual(24000, transcript["audio"]["duration_ms"])

    def test_fixture_is_fresh_and_deterministic(self):
        first, data = player.synthetic_fixture()
        baseline = copy.deepcopy(first)
        first["cues"][0]["text"] = "Changed"
        second, again = player.synthetic_fixture()
        self.assertEqual(baseline, second)
        self.assertEqual(data, again)

    def test_fixture_covers_gaps_adjacent_cues_and_trailing_silence(self):
        transcript, _ = player.synthetic_fixture()
        cues = transcript["cues"]
        self.assertGreater(cues[0]["start_ms"], 0)
        self.assertLess(cues[-1]["end_ms"], transcript["audio"]["duration_ms"])
        self.assertTrue(any(a["end_ms"] == b["start_ms"] for a, b in zip(cues, cues[1:])))
        self.assertTrue(any(a["end_ms"] < b["start_ms"] for a, b in zip(cues, cues[1:])))

    def test_generated_audio_passes_existing_candidate_measurement(self):
        transcript, wav = player.synthetic_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "demo.wav").write_bytes(wav)
            declaration = {"asset_id": transcript["audio"]["asset_id"], "size_bytes": len(wav),
                           "sha256": hashlib.sha256(wav).hexdigest()}
            registry = {"schema_version": "asset-registry-0.1", "project_id": transcript["project_id"],
                        "assets": [{**declaration, "path": "demo.wav"}]}
            candidate = {"schema_version": candidates.TRANSCRIPT_SCHEMA_VERSION,
                "project_id": transcript["project_id"], "content_id": transcript["content_id"],
                "audio": {**declaration, "duration_ms": 24000},
                "metadata": {"title": "Synthetic player fixture", "language": "ja", "credits": []},
                "transcript": {"fingerprint": transcripts.fingerprint(transcript)}}
            result = audio.measure_candidate_wav(candidate, project_id=transcript["project_id"],
                expected_fingerprint=candidates.candidate_fingerprint(candidate, project_id=transcript["project_id"]),
                registry=registry, project_root=root)
        self.assertEqual(192000, result["pcm"]["frame_count"])
        self.assertLessEqual(result["pcm"]["sample_peak_abs"][0], 1600)
        self.assertIs(True, result["duration"]["matches_declared"])
        self.assertIs(False, result["media_qa_passed"])

    def test_render_is_self_contained_and_embeds_matching_fixture(self):
        page = Page(player.render_demo())
        blocks = {attrs.get("id"): text for tag, attrs, text in page.blocks if tag == "script"}
        document = json.loads(blocks["transcript-data"])
        wav = base64.b64decode(blocks["audio-data"].split(",", 1)[1], validate=True)
        self.assertEqual(hashlib.sha256(wav).hexdigest(), document["audio"]["sha256"])
        self.assertEqual(3, sum(tag == "script" for tag, _ in page.tags))
        self.assertEqual(1, sum(tag == "audio" for tag, _ in page.tags))
        for tag, attrs in page.tags:
            self.assertNotIn("src", attrs)
            self.assertNotIn("href", attrs)
            self.assertNotIn("autoplay", attrs)
            self.assertFalse(any(name.startswith("on") for name in attrs))
            self.assertNotEqual("iframe", tag)
            self.assertNotEqual("form", tag)

    def test_content_policy_hashes_match_exact_script_and_style(self):
        page = Page(player.render_demo())
        policy = next(attrs["content"] for tag, attrs in page.tags
                      if attrs.get("http-equiv") == "Content-Security-Policy")
        self.assertIn("default-src 'none'", policy)
        self.assertIn("connect-src 'none'", policy)
        self.assertIn("media-src data:", policy)
        self.assertNotIn("unsafe-inline", policy)
        for tag, attrs, text in page.blocks:
            if tag == "style" or (tag == "script" and not attrs):
                digest = base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()
                self.assertIn(f"'sha256-{digest}'", policy)

    def test_markup_looking_cues_cannot_escape_script_data(self):
        transcript, wav = player.synthetic_fixture()
        dangerous = '</script><img src=x onerror="alert(1)">& <b>literal</b>'
        transcript["cues"][0]["text"] = dangerous
        with patch.object(player, "synthetic_fixture", return_value=(transcript, wav)):
            source = player.render_demo()
        page = Page(source)
        self.assertNotIn(dangerous, source)
        self.assertFalse(any(tag == "img" for tag, _ in page.tags))
        self.assertEqual(3, sum(tag == "script" for tag, _ in page.tags))
        data = next(text for _, attrs, text in page.blocks if attrs.get("id") == "transcript-data")
        self.assertEqual(dangerous, json.loads(data)["cues"][0]["text"])

    def test_render_is_repeatable_and_accepts_no_import_parameters(self):
        self.assertEqual(player.render_demo(), player.render_demo())
        with self.assertRaises(TypeError):
            player.render_demo("unassigned-input")

    def test_cli_emits_utf8_html_without_writing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, "-B", str(REPO / "narradock_player.py")],
                cwd=temporary, capture_output=True, check=False)
            self.assertEqual([], list(Path(temporary).iterdir()))
        self.assertEqual(0, result.returncode)
        self.assertEqual(b"", result.stderr)
        self.assertEqual(player.render_demo(), result.stdout.decode("utf-8"))

    def test_cli_rejects_arguments_without_echoing_them(self):
        result = subprocess.run([sys.executable, "-B", str(REPO / "narradock_player.py"), "private-input"],
            capture_output=True, check=False)
        self.assertEqual(2, result.returncode)
        self.assertEqual(b"", result.stdout)
        self.assertNotIn(b"private-input", result.stderr)

    def test_cli_sanitizes_output_failure(self):
        output = io.BytesIO()
        output.close()
        with patch.object(sys, "stdout") as stdout, patch.object(sys, "stderr", io.StringIO()) as stderr:
            stdout.buffer = output
            self.assertEqual(2, player.main([]))
            self.assertEqual("Synthetic player could not be rendered\n", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
