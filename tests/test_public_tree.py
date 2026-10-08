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

    def make_symlink(self, link, target, *, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except NotImplementedError:
            self.skipTest("Filesystem symlinks are not supported")
        except OSError as error:
            if getattr(error, "winerror", None) == 1314:
                self.skipTest("Windows symlink creation privilege is unavailable")
            raise

    def check_fixture(self, root, name):
        (root / "public-files.json").write_text(json.dumps([name]), encoding="utf-8")
        tracked = subprocess.CompletedProcess([], 0, stdout=(name + "\0").encode("utf-8"))
        with patch("tools.check_public_tree.subprocess.run", return_value=tracked):
            return check(root)

    def test_symlink_above_repository_root_is_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp).resolve()
            root = parent / "actual" / "repository"
            root.mkdir(parents=True)
            (root / "example.md").write_text("Neutral example.", encoding="utf-8")
            alias = parent / "alias"
            self.make_symlink(alias, root.parent, directory=True)
            self.assertEqual([], self.check_fixture(alias / "repository", "example.md"))

    def test_symlink_at_repository_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp).resolve()
            root = parent / "repository"
            root.mkdir()
            (root / "example.md").write_text("Neutral example.", encoding="utf-8")
            alias = parent / "alias"
            self.make_symlink(alias, root, directory=True)
            self.assertIn("symlink in public inventory", self.check_fixture(alias, "example.md"))

    def test_inventory_file_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp).resolve()
            root = parent / "repository"
            root.mkdir()
            target = parent / "neutral.md"
            target.write_text("Neutral example.", encoding="utf-8")
            self.make_symlink(root / "example.md", target)
            self.assertIn("symlink in public inventory", self.check_fixture(root, "example.md"))

    def test_inventory_directory_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp).resolve()
            root = parent / "repository"
            root.mkdir()
            target = parent / "neutral"
            target.mkdir()
            (target / "example.md").write_text("Neutral example.", encoding="utf-8")
            self.make_symlink(root / "docs", target, directory=True)
            self.assertIn("symlink in public inventory",
                          self.check_fixture(root, "docs/example.md"))


if __name__ == "__main__":
    unittest.main()
