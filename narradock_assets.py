"""Bounded project-local asset registries and read-only verification of actual bytes."""
from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

SCHEMA_VERSION = "asset-registry-0.1"
MAX_REGISTRY_BYTES = 256 * 1024
MAX_ASSETS = 1024
MAX_ASSET_BYTES = 16 * 1024 * 1024 * 1024
CHUNK_BYTES = 64 * 1024
MAX_PATH_LENGTH = 240
MAX_PATH_DEPTH = 16
IDENTIFIER = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
RESERVED = {"con", "prn", "aux", "nul", "conin$", "conout$"} | {
    f"{prefix}{number}" for prefix in ("com", "lpt") for number in range(1, 10)
}


class AssetError(ValueError):
    """A fixed diagnostic category, never a supplied path or file content."""


def _identifier(value: Any) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= 64
            and IDENTIFIER.fullmatch(value) is not None)


def _object(value: Any, fields: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != fields:
        raise AssetError("Invalid registry fields")


def _parts(value: Any) -> tuple[str, ...]:
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_PATH_LENGTH:
        raise AssetError("Invalid relative asset path")
    parts = tuple(value.split("/"))
    if len(parts) > MAX_PATH_DEPTH or any(
        not COMPONENT.fullmatch(part) or part.endswith(".")
        or part.split(".", 1)[0].lower() in RESERVED for part in parts
    ):
        raise AssetError("Invalid relative asset path")
    return parts


def _entries(document: Any, project_id: str) -> dict[str, tuple[tuple[str, ...], int, str]]:
    _object(document, {"schema_version", "project_id", "assets"})
    if document["schema_version"] != SCHEMA_VERSION:
        raise AssetError("Unsupported registry schema")
    if not _identifier(project_id) or not _identifier(document["project_id"]):
        raise AssetError("Invalid project identifier")
    if document["project_id"] != project_id:
        raise AssetError("Registry project mismatch")
    assets = document["assets"]
    if not isinstance(assets, list) or not 1 <= len(assets) <= MAX_ASSETS:
        raise AssetError("Invalid asset count")
    entries = {}
    paths = set()
    for asset in assets:
        _object(asset, {"asset_id", "path", "size_bytes", "sha256"})
        asset_id = asset["asset_id"]
        if not _identifier(asset_id) or asset_id in entries:
            raise AssetError("Invalid or duplicate asset identifier")
        parts = _parts(asset["path"])
        portable = tuple(part.lower() for part in parts)
        if portable in paths:
            raise AssetError("Duplicate asset path")
        size, digest = asset["size_bytes"], asset["sha256"]
        if type(size) is not int or not 0 <= size <= MAX_ASSET_BYTES:
            raise AssetError("Invalid asset size")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise AssetError("Invalid asset digest")
        paths.add(portable)
        entries[asset_id] = (parts, size, digest)
    if any(path[:length] in paths for path in paths for length in range(1, len(path))):
        raise AssetError("Conflicting asset paths")
    return entries


def validate_registry(document: Any, *, project_id: str) -> None:
    """Check only structure and declared project; no assets are opened."""
    _entries(document, project_id)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise AssetError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise AssetError("Non-finite JSON value")


def _stamp(info: os.stat_result) -> tuple[int, ...]:
    # atime may legitimately change because of this read.
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            getattr(info, "st_file_attributes", 0))


def _node(info: os.stat_result, *, directory: bool) -> None:
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise AssetError("Links or reparse points are not allowed")
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise AssetError("Unexpected filesystem object type")
    if not directory and info.st_nlink != 1:
        raise AssetError("Hard-linked assets are not allowed")


@contextmanager
def _windows_node(path: Path, *, directory: bool):
    """Pin directories against rename; deny concurrent writers on the file."""
    import ctypes
    from ctypes import wintypes
    import msvcrt

    class FileInfo(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("creation", wintypes.FILETIME),
                    ("access", wintypes.FILETIME), ("write", wintypes.FILETIME),
                    ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                    ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                    ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    api.CreateFileW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    api.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInfo)]
    api.GetFileInformationByHandle.restype = wintypes.BOOL
    api.GetFileType.argtypes = [wintypes.HANDLE]
    api.GetFileType.restype = wintypes.DWORD
    # OPEN_REPARSE_POINT prevents following the final component. Held ancestor
    # handles omit SHARE_DELETE, so a checked directory cannot be swapped out.
    flags = 0x00200000 | (0x02000000 if directory else 0)
    handle = api.CreateFileW(str(path), 0x80 if directory else 0x80000000,
                             3 if directory else 1, None, 3, flags, None)
    if handle == ctypes.c_void_p(-1).value:
        raise AssetError("Filesystem object could not be opened")
    fd = None
    try:
        info = FileInfo()
        if api.GetFileType(handle) != 1 or not api.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise AssetError("Unexpected filesystem object type")
        if info.attributes & 0x400:
            raise AssetError("Links or reparse points are not allowed")
        if bool(info.attributes & 0x10) != directory:
            raise AssetError("Unexpected filesystem object type")
        if not directory:
            if info.links != 1:
                raise AssetError("Hard-linked assets are not allowed")
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        yield fd, info.volume
    finally:
        if fd is not None:
            os.close(fd)
        else:
            api.CloseHandle(handle)


@contextmanager
def _direct_file(path: Path):
    before = path.lstat()
    _node(before, directory=False)
    with ExitStack() as stack:
        if os.name == "nt":
            fd, _ = stack.enter_context(_windows_node(path, directory=False))
        else:
            if not hasattr(os, "O_NOFOLLOW"):
                raise AssetError("Unsupported filesystem platform")
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            stack.callback(os.close, fd)
        opened = os.fstat(fd)
        _node(opened, directory=False)
        if _stamp(before) != _stamp(opened):
            raise AssetError("Filesystem object changed during verification")
        yield fd
        if _stamp(opened) != _stamp(os.fstat(fd)) or _stamp(opened) != _stamp(path.lstat()):
            raise AssetError("Filesystem object changed during verification")


def load_registry(path: Path, *, project_id: str) -> dict[str, Any]:
    """Read the explicit registry file, bounded and independently of asset roots."""
    try:
        with _direct_file(Path(path)) as fd:
            data = bytearray()
            while len(data) <= MAX_REGISTRY_BYTES:
                chunk = os.read(fd, min(CHUNK_BYTES, MAX_REGISTRY_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
        if len(data) > MAX_REGISTRY_BYTES:
            raise AssetError("Registry exceeds size limit")
        document = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object,
                              parse_constant=_reject_constant)
        validate_registry(document, project_id=project_id)
        return document
    except AssetError:
        raise
    except (OSError, ValueError, TypeError, RecursionError):
        raise AssetError("Registry could not be read as valid UTF-8 JSON") from None


@contextmanager
def _asset_fd(root: Path, parts: tuple[str, ...]):
    if not root.is_absolute() or ".." in root.parts:
        raise AssetError("An absolute trusted project root is required")
    if os.name == "nt" and not re.fullmatch(r"[A-Za-z]:", root.drive):
        raise AssetError("A local drive project root is required")
    paths = [root]
    for part in parts:
        paths.append(paths[-1] / part)
    snapshots = []
    with ExitStack() as stack:
        if os.name == "nt":
            volume = None
            for index, path in enumerate(paths):
                directory = index < len(paths) - 1
                fd, device = stack.enter_context(_windows_node(path, directory=directory))
                if volume is None:
                    volume = device
                if device != volume:
                    raise AssetError("Filesystem boundary crossed")
                info = path.lstat()
                _node(info, directory=directory)
                snapshots.append(_stamp(info))
        elif (os.name == "posix" and os.open in os.supports_dir_fd
              and hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY")):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
            parent = os.open(root, flags)
            stack.callback(os.close, parent)
            root_info = os.fstat(parent)
            _node(root_info, directory=True)
            snapshots.append(_stamp(root_info))
            for index, part in enumerate(parts):
                directory = index < len(parts) - 1
                before = os.stat(part, dir_fd=parent, follow_symlinks=False)
                _node(before, directory=directory)
                fd = os.open(part, flags if directory else
                             os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                stack.callback(os.close, fd)
                info = os.fstat(fd)
                _node(info, directory=directory)
                if _stamp(before) != _stamp(info):
                    raise AssetError("Filesystem object changed during verification")
                if info.st_dev != root_info.st_dev:
                    raise AssetError("Filesystem boundary crossed")
                snapshots.append(_stamp(info))
                parent = fd
        else:
            raise AssetError("Unsupported filesystem platform")
        # Compare the pinned object with its current path before and after reads.
        opened = os.fstat(fd)
        _node(opened, directory=False)
        if _stamp(opened) != snapshots[-1]:
            raise AssetError("Filesystem object changed during verification")
        for path, snapshot in zip(paths, snapshots):
            if _stamp(path.lstat()) != snapshot:
                raise AssetError("Filesystem object changed during verification")
        yield fd
        if _stamp(os.fstat(fd)) != _stamp(opened):
            raise AssetError("Asset changed during verification")
        for path, snapshot in zip(paths, snapshots):
            if _stamp(path.lstat()) != snapshot:
                raise AssetError("Filesystem object changed during verification")


def verify_asset(document: Any, *, project_root: Path, project_id: str,
                 asset_id: str) -> dict[str, Any]:
    """Verify one declared asset's bytes now; never cache or return a reusable path."""
    try:
        entries = _entries(document, project_id)
        if not _identifier(asset_id) or asset_id not in entries:
            raise AssetError("Unknown asset reference")
        parts, size, expected = entries[asset_id]
        with _asset_fd(Path(project_root), parts) as fd:
            if os.fstat(fd).st_size != size:
                raise AssetError("Asset size mismatch")
            digest = hashlib.sha256()
            total = 0
            while total <= size:
                chunk = os.read(fd, min(CHUNK_BYTES, size + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                digest.update(chunk)
            if total != size:
                raise AssetError("Asset size mismatch")
            actual = digest.hexdigest()
            if actual != expected:
                raise AssetError("Asset digest mismatch")
        return {"verified": True, "scope": "asset_bytes_only", "project_id": project_id,
                "asset_id": asset_id, "size_bytes": total, "sha256": actual,
                "rights_verified": False, "media_qa_passed": False,
                "external_transfer": False, "publication": False}
    except AssetError:
        raise
    except (OSError, ValueError, TypeError, RecursionError):
        raise AssetError("Asset could not be verified") from None


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise AssetError("Invalid command arguments")


def main(argv: list[str] | None = None) -> int:
    try:
        parser = _Parser(description=__doc__)
        parser.add_argument("command", choices=("validate", "verify"))
        parser.add_argument("registry", type=Path)
        parser.add_argument("--project-id", required=True)
        parser.add_argument("--project-root", type=Path)
        parser.add_argument("--asset-id")
        args = parser.parse_args(argv)
        if args.command == "verify" and (args.project_root is None or args.asset_id is None):
            raise AssetError("Verification requires project root and asset identifier")
        if args.command == "validate" and (args.project_root is not None or args.asset_id is not None):
            raise AssetError("Structural validation does not accept asset arguments")
        registry = load_registry(args.registry, project_id=args.project_id)
        result = (verify_asset(registry, project_root=args.project_root,
                               project_id=args.project_id, asset_id=args.asset_id)
                  if args.command == "verify" else
                  {"valid": True, "scope": "structure_only", "bytes_verified": False,
                   "external_transfer": False, "publication": False})
        sys.stdout.write(json.dumps(result, sort_keys=True, indent=2) + "\n")
        sys.stdout.flush()
    except AssetError as error:
        print(f"Invalid assets: {error}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError):
        # A broken output must not fail again during interpreter shutdown.
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())
        print("Invalid assets: Output could not be written", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
