"""Synthetic asset-byte tests; no media, providers, or production workspaces."""
import copy
import errno
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import narradock_assets as assets

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "narradock_assets.py"


class AssetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.parent = Path(temporary.name).resolve()
        self.root = self.parent / "project"
        self.root.mkdir()
        (self.root / "inputs").mkdir()
        self.data = b"Neutral synthetic asset bytes.\n"
        self.file = self.root / "inputs" / "sample.dat"
        self.file.write_bytes(self.data)
        self.document = self.registry("project-one", self.data)
        self.registry_file = self.parent / "registry.json"
        self.registry_file.write_text(json.dumps(self.document), encoding="utf-8")

    def registry(self, project, data):
        return {"schema_version": assets.SCHEMA_VERSION, "project_id": project,
                "assets": [{"asset_id": "sample-input", "path": "inputs/sample.dat",
                            "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}]}

    def verify(self, document=None, root=None, project="project-one"):
        return assets.verify_asset(self.document if document is None else document,
                                   project_root=self.root if root is None else root,
                                   project_id=project, asset_id="sample-input")

    def reject(self, document):
        with self.assertRaises(assets.AssetError):
            assets.validate_registry(document, project_id="project-one")

    def symlink(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except NotImplementedError:
            self.skipTest("Filesystem symlinks unavailable")
        except OSError as error:
            if getattr(error, "winerror", None) == 1314:
                self.skipTest("Windows symlink creation privilege unavailable")
            raise

    def test_structure_does_not_verify_or_open_asset(self):
        self.file.unlink()
        assets.validate_registry(self.document, project_id="project-one")
        loaded = assets.load_registry(self.registry_file, project_id="project-one")
        self.assertEqual(self.document, loaded)
        with self.assertRaises(assets.AssetError):
            self.verify(loaded)

    def test_actual_bytes_and_receipt_boundaries(self):
        before = copy.deepcopy(self.document)
        result = self.verify()
        self.assertIs(True, result["verified"])
        self.assertEqual("asset_bytes_only", result["scope"])
        self.assertEqual(hashlib.sha256(self.data).hexdigest(), result["sha256"])
        self.assertEqual(len(self.data), result["size_bytes"])
        for key in ("rights_verified", "media_qa_passed", "external_transfer", "publication"):
            self.assertIs(False, result[key])
        self.assertNotIn("path", result)
        self.assertEqual(before, self.document)
        self.assertEqual(self.data, self.file.read_bytes())

    def test_empty_and_multichunk_assets(self):
        for data in (b"", b"z" * (assets.CHUNK_BYTES * 3 + 17)):
            with self.subTest(size=len(data)):
                self.file.write_bytes(data)
                self.assertEqual(len(data), self.verify(self.registry("project-one", data))["size_bytes"])

    def test_read_sizes_are_bounded(self):
        data = b"q" * (assets.CHUNK_BYTES * 2 + 3)
        self.file.write_bytes(data)
        original = os.read
        sizes = []
        def read(fd, count):
            sizes.append(count)
            return original(fd, count)
        with patch("narradock_assets.os.read", side_effect=read):
            self.verify(self.registry("project-one", data))
        self.assertGreater(len(sizes), 2)
        self.assertTrue(all(0 < count <= assets.CHUNK_BYTES for count in sizes))

    def test_schema_and_container_types(self):
        for value in (None, [], "registry", 1, True):
            self.reject(value)
        for value in (None, 1, True, "unknown-version"):
            self.reject(dict(self.document, schema_version=value))
        for value in (None, {}, "assets", True):
            self.reject(dict(self.document, assets=value))
        self.reject(dict(self.document, assets=[None]))

    def test_unknown_and_missing_fields(self):
        for key in [*self.document, "extra"]:
            value = copy.deepcopy(self.document)
            if key == "extra": value[key] = True
            else: del value[key]
            self.reject(value)
        for key in [*self.document["assets"][0], "extra"]:
            value = copy.deepcopy(self.document)
            if key == "extra": value["assets"][0][key] = True
            else: del value["assets"][0][key]
            self.reject(value)

    def test_project_and_asset_identifiers(self):
        for value in (None, True, "", "Project", "a--b", "a" * 65, "../sample", []):
            self.reject(dict(self.document, project_id=value))
            changed = copy.deepcopy(self.document)
            changed["assets"][0]["asset_id"] = value
            self.reject(changed)

    def test_project_mismatch_and_unknown_reference(self):
        with self.assertRaisesRegex(assets.AssetError, "project mismatch"):
            self.verify(project="project-two")
        for reference in ("unknown", "../sample", None, []):
            with self.assertRaises(assets.AssetError):
                assets.verify_asset(self.document, project_root=self.root,
                                    project_id="project-one", asset_id=reference)

    def test_duplicate_asset_ids_and_case_ambiguous_paths(self):
        for changes in ({}, {"asset_id": "other"},
                        {"asset_id": "other", "path": "INPUTS/SAMPLE.DAT"}):
            document = copy.deepcopy(self.document)
            document["assets"].append(dict(document["assets"][0], **changes))
            self.reject(document)

    def test_file_and_directory_path_conflict(self):
        document = copy.deepcopy(self.document)
        document["assets"].append(dict(document["assets"][0], asset_id="other", path="inputs"))
        self.reject(document)

    def test_unsafe_paths_are_rejected_portably(self):
        paths = ["", ".", "..", "../sample", "inputs/../sample", "/sample", "//server/sample",
                 "inputs//sample", "inputs/./sample", "inputs/", "inputs\\sample",
                 "C:/sample", "C:sample", "sample:stream", "sample.", "sample ", "NUL",
                 "con.txt", "inputs/COM1.dat", "lpt9", "a\x00b", "a\nb", "a%2fb", "素材.dat",
                 "a" * (assets.MAX_PATH_LENGTH + 1), "/".join(["a"] * (assets.MAX_PATH_DEPTH + 1))]
        for path in paths:
            with self.subTest(path=repr(path)):
                document = copy.deepcopy(self.document)
                document["assets"][0]["path"] = path
                self.reject(document)

    def test_size_and_digest_bounds(self):
        for size in (-1, True, 1.0, "1", assets.MAX_ASSET_BYTES + 1):
            document = copy.deepcopy(self.document)
            document["assets"][0]["size_bytes"] = size
            self.reject(document)
        for digest in ("a" * 63, "A" * 64, "g" * 64, None, []):
            document = copy.deepcopy(self.document)
            document["assets"][0]["sha256"] = digest
            self.reject(document)

    def test_count_bounds(self):
        self.reject(dict(self.document, assets=[]))
        self.reject(dict(self.document, assets=[{}] * (assets.MAX_ASSETS + 1)))

    def test_duplicate_json_keys_at_each_level(self):
        raw = json.dumps(self.document)
        cases = [raw.replace('"project_id":', '"project_id":"other", "project_id":'),
                 raw.replace('"size_bytes":', '"size_bytes":0, "size_bytes":')]
        for text in cases:
            self.registry_file.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(assets.AssetError, "Duplicate JSON key"):
                assets.load_registry(self.registry_file, project_id="project-one")

    def test_malformed_encoding_constants_and_deep_json(self):
        cases = [b"\xff", b"{", b"[]", b'{"x":NaN}', b'{"x":Infinity}',
                 b"[" * 2000 + b"]" * 2000, b'\xef\xbb\xbf{}']
        for raw in cases:
            self.registry_file.write_bytes(raw)
            with self.assertRaises(assets.AssetError):
                assets.load_registry(self.registry_file, project_id="project-one")

    def test_oversized_registry_and_integer(self):
        cases = [b" " * (assets.MAX_REGISTRY_BYTES + 1), b'{"x":' + b"9" * 5000 + b'}']
        for raw in cases:
            self.registry_file.write_bytes(raw)
            with self.assertRaises(assets.AssetError):
                assets.load_registry(self.registry_file, project_id="project-one")

    def test_registry_read_is_bounded(self):
        self.registry_file.write_bytes(b" " * (assets.MAX_REGISTRY_BYTES * 2))
        original = os.read
        count = 0
        def read(fd, size):
            nonlocal count
            data = original(fd, size)
            count += len(data)
            return data
        with patch("narradock_assets.os.read", side_effect=read):
            with self.assertRaises(assets.AssetError):
                assets.load_registry(self.registry_file, project_id="project-one")
        self.assertEqual(assets.MAX_REGISTRY_BYTES + 1, count)

    def test_missing_files_and_nonregular_registry(self):
        self.file.unlink()
        with self.assertRaises(assets.AssetError): self.verify()
        for path in (self.parent / "missing-private-marker", self.root):
            with self.assertRaises(assets.AssetError) as caught:
                assets.load_registry(path, project_id="project-one")
            self.assertNotIn(str(path), str(caught.exception))

    def test_size_and_hash_mismatches(self):
        self.file.write_bytes(self.data + b"x")
        with self.assertRaisesRegex(assets.AssetError, "size mismatch"): self.verify()
        self.file.write_bytes(b"x" * len(self.data))
        with self.assertRaisesRegex(assets.AssetError, "digest mismatch"): self.verify()

    def test_two_projects_reuse_id_without_cache_or_state(self):
        second = self.parent / "second-project"
        (second / "inputs").mkdir(parents=True)
        other = b"Different neutral bytes."
        (second / "inputs/sample.dat").write_bytes(other)
        document = self.registry("project-two", other)
        self.assertEqual(hashlib.sha256(self.data).hexdigest(), self.verify()["sha256"])
        self.assertEqual(hashlib.sha256(other).hexdigest(),
                         self.verify(document, second, "project-two")["sha256"])
        with self.assertRaises(assets.AssetError): self.verify(document, self.root, "project-two")
        with self.assertRaises(assets.AssetError): self.verify(self.document, second)
        self.file.write_bytes(b"x" * len(self.data))
        with self.assertRaises(assets.AssetError): self.verify()

    def test_relative_and_traversing_root_rejected(self):
        for root in (Path("relative-project"), self.root / ".." / "project"):
            with self.assertRaises(assets.AssetError): self.verify(root=root)

    def test_asset_directory_rejected(self):
        self.file.unlink()
        self.file.mkdir()
        with self.assertRaises(assets.AssetError): self.verify()

    def test_file_symlink_rejected_even_when_inside_root(self):
        target = self.root / "neutral.dat"
        target.write_bytes(self.data)
        self.file.unlink()
        self.symlink(self.file, target)
        with self.assertRaises(assets.AssetError): self.verify()

    def test_directory_symlink_escape_rejected(self):
        outside = self.parent / "outside"
        outside.mkdir()
        (outside / "sample.dat").write_bytes(self.data)
        self.file.unlink()
        self.file.parent.rmdir()
        self.symlink(self.file.parent, outside, directory=True)
        with self.assertRaises(assets.AssetError): self.verify()

    def test_root_symlink_rejected(self):
        alias = self.parent / "alias"
        self.symlink(alias, self.root, directory=True)
        with self.assertRaises(assets.AssetError): self.verify(root=alias)

    def test_registry_symlink_rejected(self):
        alias = self.parent / "registry-alias.json"
        self.symlink(alias, self.registry_file)
        with self.assertRaises(assets.AssetError):
            assets.load_registry(alias, project_id="project-one")

    def test_hard_link_rejected(self):
        try:
            os.link(self.file, self.parent / "alias.dat")
        except OSError as error:
            if error.errno in (errno.ENOSYS, errno.ENOTSUP):
                self.skipTest("Filesystem hard links unavailable")
            raise
        with self.assertRaisesRegex(assets.AssetError, "Hard-linked"): self.verify()

    @unittest.skipUnless(os.name == "posix", "POSIX FIFO case")
    def test_fifo_rejected_without_blocking(self):
        self.file.unlink()
        os.mkfifo(self.file)
        with self.assertRaises(assets.AssetError): self.verify()
        self.registry_file.unlink()
        os.mkfifo(self.registry_file)
        with self.assertRaises(assets.AssetError):
            assets.load_registry(self.registry_file, project_id="project-one")

    @unittest.skipUnless(os.name == "posix", "POSIX concurrent replacement case")
    def test_replaced_file_during_read_rejected(self):
        original = os.read
        changed = False
        def read(fd, size):
            nonlocal changed
            data = original(fd, size)
            if not changed:
                changed = True
                self.file.rename(self.root / "original.dat")
                self.file.write_bytes(self.data)
            return data
        with patch("narradock_assets.os.read", side_effect=read):
            with self.assertRaisesRegex(assets.AssetError, "changed"): self.verify()

    @unittest.skipUnless(os.name == "posix", "POSIX concurrent mutation case")
    def test_in_place_change_during_read_rejected(self):
        original = os.read
        changed = False
        def read(fd, size):
            nonlocal changed
            data = original(fd, size)
            if not changed:
                changed = True
                self.file.write_bytes(b"x" * len(self.data))
            return data
        with patch("narradock_assets.os.read", side_effect=read):
            with self.assertRaisesRegex(assets.AssetError, "changed"): self.verify()

    @unittest.skipUnless(os.name == "posix", "POSIX no-follow race case")
    def test_symlink_swap_before_open_does_not_read_target(self):
        outside = self.parent / "outside.dat"
        outside.write_bytes(self.data)
        original = os.stat
        def inspect(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == "sample.dat":
                self.file.unlink()
                self.file.symlink_to(outside)
            return info
        with patch("narradock_assets.os.stat", side_effect=inspect):
            with patch("narradock_assets.os.read") as read:
                with self.assertRaises(assets.AssetError): self.verify()
                read.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "POSIX growing input case")
    def test_growing_file_read_stops_at_declared_size_plus_one(self):
        original = os.read
        total = 0
        def read(fd, size):
            nonlocal total
            with self.file.open("ab") as stream:
                stream.write(b"x" * 1000)
            data = original(fd, size)
            total += len(data)
            return data
        with patch("narradock_assets.os.read", side_effect=read):
            with self.assertRaisesRegex(assets.AssetError, "size mismatch"): self.verify()
        self.assertEqual(len(self.data) + 1, total)

    @unittest.skipUnless(os.name == "posix", "POSIX concurrent directory replacement case")
    def test_replaced_parent_during_read_rejected(self):
        original = os.read
        changed = False
        def read(fd, size):
            nonlocal changed
            data = original(fd, size)
            if not changed:
                changed = True
                self.file.parent.rename(self.root / "old-inputs")
                self.file.parent.mkdir()
                self.file.write_bytes(self.data)
            return data
        with patch("narradock_assets.os.read", side_effect=read):
            with self.assertRaisesRegex(assets.AssetError, "changed"): self.verify()

    @unittest.skipUnless(os.name == "nt", "Windows junction case")
    def test_windows_junction_escape_rejected(self):
        outside = self.parent / "outside"
        outside.mkdir()
        (outside / "sample.dat").write_bytes(self.data)
        self.file.unlink()
        self.file.parent.rmdir()
        result = subprocess.run(["cmd", "/d", "/c", "mklink", "/J",
                                 str(self.file.parent), str(outside)], capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.addCleanup(os.rmdir, self.file.parent)
        with self.assertRaisesRegex(assets.AssetError, "reparse"): self.verify()

    @unittest.skipUnless(os.name == "nt", "Windows writer-sharing case")
    def test_windows_open_asset_denies_writer(self):
        original = os.read
        attempts = []
        def read(fd, size):
            with self.assertRaises(PermissionError): self.file.write_bytes(b"changed")
            attempts.append(True)
            return original(fd, size)
        with patch("narradock_assets.os.read", side_effect=read): self.verify()
        self.assertTrue(attempts)

    @unittest.skipUnless(os.name == "nt", "Windows ancestor-sharing case")
    def test_windows_open_parent_denies_rename(self):
        original = os.read
        attempts = []
        def read(fd, size):
            with self.assertRaises(PermissionError): self.file.parent.rename(self.root / "moved")
            attempts.append(True)
            return original(fd, size)
        with patch("narradock_assets.os.read", side_effect=read): self.verify()
        self.assertTrue(attempts)

    def test_io_error_diagnostic_does_not_echo_source(self):
        with patch("narradock_assets.os.read", side_effect=OSError("private-value-marker")):
            with self.assertRaises(assets.AssetError) as caught: self.verify()
        self.assertEqual("Asset could not be verified", str(caught.exception))

    def test_cli_validate_and_verify_are_distinct(self):
        common = [sys.executable, "-B", str(CLI)]
        for command, extra in [("validate", []), ("verify", ["--project-root", str(self.root),
                                                            "--asset-id", "sample-input"])]:
            result = subprocess.run(common + [command, str(self.registry_file), "--project-id",
                                              "project-one"] + extra, capture_output=True)
            self.assertEqual(0, result.returncode, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual("structure_only" if command == "validate" else "asset_bytes_only", value["scope"])
            self.assertNotIn(str(self.root).encode(), result.stdout)
            self.assertIs(False, value["publication"])
        self.assertEqual(self.data, self.file.read_bytes())
        self.assertEqual(["inputs"], sorted(p.name for p in self.root.iterdir()))

    def test_cli_errors_are_sanitized(self):
        for args in [["unknown-private-marker"], ["validate", str(self.parent / "private-marker"),
                     "--project-id", "project-one"], ["verify", str(self.registry_file),
                     "--project-id", "project-one"], ["validate", str(self.registry_file),
                     "--project-id", "project-one", "--project-root", str(self.root)]]:
            result = subprocess.run([sys.executable, "-B", str(CLI)] + args, capture_output=True)
            self.assertEqual(2, result.returncode)
            self.assertEqual(b"", result.stdout)
            self.assertNotIn(b"private-marker", result.stderr)
            self.assertNotIn(str(self.parent).encode(), result.stderr)
            self.assertNotIn(b"Traceback", result.stderr)

    def test_cli_closed_pipe_returns_safe_error(self):
        read_fd, write_fd = os.pipe()
        os.close(read_fd)
        try:
            result = subprocess.run([sys.executable, "-E", "-B", str(CLI), "validate",
                                     str(self.registry_file), "--project-id", "project-one"],
                                    stdout=write_fd, stderr=subprocess.PIPE, timeout=10)
        finally:
            os.close(write_fd)
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertEqual([b"Invalid assets: Output could not be written"], result.stderr.splitlines())


if __name__ == "__main__":
    unittest.main()
