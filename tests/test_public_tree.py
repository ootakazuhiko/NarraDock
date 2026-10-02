from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import json

from tools.check_public_tree import ROOT, check, inspect_text


class PublicTreeTests(unittest.TestCase):
    def test_repository_inventory(self):
        self.assertEqual([], check(ROOT))

    def test_neutral_text(self):
        self.assertEqual([], inspect_text("example.md", "A neutral example."))

    def test_binary_type_rejected(self):
        self.assertTrue(inspect_text("example.mp4", "neutral"))

    def test_nul_rejected(self):
        self.assertTrue(inspect_text("example.md", "text" + chr(0)))

    def test_token_shape_rejected(self):
        token = "gh" + "p_" + "x" * 40
        self.assertTrue(inspect_text("example.md", token))

    def test_private_key_marker_rejected(self):
        text = "-----BEGIN " + "PRIVATE KEY-----"
        self.assertTrue(inspect_text("example.md", text))

    def test_workstation_path_rejected(self):
        text = "Z:" + chr(92) + "Users" + chr(92) + "example"
        self.assertTrue(inspect_text("example.md", text))

    def test_inventory_mismatch_rejected(self):
        result = subprocess.CompletedProcess([], 0, stdout=b"unexpected.md\0")
        with patch("tools.check_public_tree.subprocess.run", return_value=result):
            self.assertIn("tracked files differ from public inventory", check(ROOT))

    def test_unsafe_inventory_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "public-files.json").write_text(json.dumps(["../outside.md"]), encoding="utf-8")
            result = subprocess.CompletedProcess([], 0, stdout=b"../outside.md\0")
            with patch("tools.check_public_tree.subprocess.run", return_value=result):
                self.assertIn("unsafe inventory path", check(root))


if __name__ == "__main__":
    unittest.main()
