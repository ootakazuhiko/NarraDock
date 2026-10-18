# Project-local asset registry 0.1

`narradock_assets.py` validates a bounded registry and verifies one explicitly
selected local file by streaming its actual bytes. It uses Python 3.11+ and the
standard library. It does not import a media engine, decode audio, synthesize,
render, cache, modify an asset, transfer data, or authorize publication.

## Trust and project assignment

The caller independently supplies the expected project ID, trusted absolute
project root, registry file, and requested asset ID. Do not obtain the root or
expected project ID from untrusted registry contents. Project names are scoped
labels, not authentication. A caller that supplies another project's root has
already crossed the authorization boundary; this module cannot infer ownership.

The registry file is an explicit input and may be outside the project root. Only
that file is read by the loader. Its embedded paths are interpreted beneath the
explicit project root when verification is requested. There are no global asset
IDs, implicit search directories, persistent receipts, or shared caches. Two
projects can use the same asset ID without reusing each other's state.

The root and its ancestors, mount topology, and registry assignment must be under
trusted control. Do not let untrusted users concurrently restructure this tree.
This is defensive file verification, not an OS sandbox, permission system, or
guarantee against every filesystem race. Use OS permissions/isolation as needed.

## Strict schema

Every listed field is required; unknown fields fail. JSON is UTF-8 without a BOM.
Duplicate keys at any level, non-finite values, malformed JSON and excessive
nesting are rejected. The file loader reads at most 256 KiB plus one limit probe
byte. Direct in-memory validation enforces field/count limits, not a serialized
JSON byte limit.

| Field | Contract |
|---|---|
| schema_version | Exactly `asset-registry-0.1` |
| project_id | Matches the caller's expected ID |
| assets | List of 1 to 1,024 asset records |
| assets[].asset_id | Unique within this project registry |
| assets[].path | Portable relative file path beneath the supplied root |
| assets[].size_bytes | Integer, not bool; 0 through 16 GiB inclusive |
| assets[].sha256 | Exactly 64 lowercase hexadecimal characters |

Project and asset IDs start with a lowercase letter and use lowercase letters,
digits, and single separating hyphens; maximum length is 64. Paths have at most
240 characters and 16 slash-separated components. Components start with an ASCII
letter or digit and otherwise use ASCII letters/digits, dots, underscores, and
hyphens. Empty components, dot traversal, absolute/drive/UNC paths, backslashes,
colons/alternate streams, trailing dots/spaces, control characters, Unicode path
aliases, and Windows device names are rejected on every OS. This deliberately
restricted portable subset is versioned; filenames outside it need explicit
renaming or a future contract, not silent normalization.

Paths are unique ignoring ASCII case, and a declared file cannot also be another
entry's directory prefix. A syntactically valid digest is only a declaration.
Structural validation never reports actual bytes as verified.

## API

```python
from pathlib import Path
from narradock_assets import load_registry, validate_registry, verify_asset

# The application supplies these values from its own trusted project assignment.
# document = load_registry(registry_path, project_id=expected_project_id)
# validate_registry(document, project_id=expected_project_id)
# receipt = verify_asset(document, project_root=absolute_project_root,
#                        project_id=expected_project_id, asset_id=selected_asset_id)
```

`validate_registry` returns `None` on structural success. `load_registry` returns
the validated dictionary. `verify_asset` revalidates the entire registry and
copies the selected path/size/digest into an immutable tuple before opening the
file. It returns a dictionary only after the stream and final stability checks
pass. All public failures use `AssetError` with fixed messages, without echoing
paths, original I/O errors, registry values or asset contents.

A successful receipt has `verified=true`, `scope=asset_bytes_only`, the project
and asset IDs, measured `size_bytes` and actual `sha256`. It always retains
`rights_verified=false`, `media_qa_passed=false`, `external_transfer=false` and
`publication=false`. IDs in success receipts are caller-selected opaque labels;
do not use sensitive content as labels. No resolved filename is returned.

The receipt is an observation of the bytes just read. It is not a reusable file
handle, immutable snapshot, permission token, or guarantee about a later open.
Reverify at the point of consumption; binding verified bytes to a later renderer
or immutable release package is a separate implementation.

## CLI and a reproducible synthetic example

Structural validation needs no assets:

```text
python -B narradock_assets.py validate examples/asset-registry.json --project-id sample-project
```

Expected: exit 0, `scope=structure_only`, `bytes_verified=false`; no files created.
The example declares `inputs/example.dat` containing exactly the 23 bytes of
`b"Neutral asset example.\n"`. The file is not shipped as a media fixture. The
following Python snippet creates only temporary synthetic bytes and verifies the
checked-in example through the API:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from narradock_assets import load_registry, verify_asset

document = load_registry(Path("examples/asset-registry.json"),
                         project_id="sample-project")
with TemporaryDirectory() as directory:
    root = Path(directory).resolve()
    (root / "inputs").mkdir()
    (root / "inputs" / "example.dat").write_bytes(b"Neutral asset example.\n")
    receipt = verify_asset(document, project_root=root,
                           project_id="sample-project", asset_id="sample-input")
    assert receipt["verified"] and receipt["size_bytes"] == 23
    assert receipt["publication"] is False
```

The CLI verification form is `verify REGISTRY --project-id PROJECT
--project-root ABSOLUTE_ROOT --asset-id ASSET`; uppercase values are placeholders
for the caller's assigned inputs. All arguments are explicit. Verification needs
both root and asset ID; `validate` rejects these asset-only arguments. Success is
exit 0; invalid input, failed verification or failed output is exit 2 with a fixed
diagnostic. A closed output pipe does not become an unhandled shutdown error.
Use `python3` if that is the verified Python 3.11+ executable in the environment.
No production or Windows workstation is assigned by these examples.

## Filesystem protection and limits

- All symlinks and Windows reparse points, including in-root aliases and the root
  itself, are rejected. Multi-link regular files are also rejected. Directories,
  FIFOs, devices and other non-regular assets fail before byte reads.
- POSIX traversal holds directory descriptors and opens each next component with
  `dir_fd` and `O_NOFOLLOW`; directories require `O_DIRECTORY`. File opens use
  `O_NONBLOCK` so a raced FIFO cannot hang the verifier. Unsupported platforms
  fail rather than silently dropping these protections. Cross-device entries
  fail; same-device bind mounts are not an ownership boundary and require trusted
  mount topology.
- Windows uses native `CreateFileW` with `OPEN_REPARSE_POINT`, checks handle
  attributes/type, and pins every directory from the root down without delete
  sharing. The file is opened without write/delete sharing. Conflicting writers
  cause a failure; the verifier does not terminate or modify their processes.
  Root paths must be absolute local drive paths; UNC/network/device roots fail.
- The verifier checks identity, type, link count, size and modification/change
  timestamps before and after reading, excluding read-induced access time.
  Current path identities are compared with the opened objects. Detected changes
  fail; Windows sharing locks additionally prevent tested replacements/writes.
- Reads are at most 64 KiB, with at most declared size plus one byte consumed.
  Initial size, final size, streamed byte count and digest must agree. There is
  no full-asset allocation. Empty files are supported. Slow filesystem reads have
  no hard deadline; the 16 GiB cap is a byte bound, not a latency guarantee.
- Root ancestors are caller-trusted. Privileged actors, malicious filesystems,
  metadata-preserving changes, changes after return, and races outside tested
  windows are not comprehensively excluded. This release neither snapshots
  content nor certifies production isolation. Windows timestamp semantics differ
  from POSIX; sharing protection is not replaced by timestamp equality.

## Tests and scope

Run the complete existing development validation sequence plus the structural
example command above. New tests generate neutral temporary byte strings only.
They cover strict input limits, duplicate keys/IDs/paths, actual hashes, streaming
bounds, project mixing, failures without raw paths, aliases, non-regular files,
read-time changes, and CLI behavior. POSIX-only FIFO/replacement/race cases and
Windows-only junction/sharing cases report explicit skips on the opposite OS.
Symlink privilege or unsupported hard-link capabilities also produce explicit
skips; other setup errors fail. CI counts and skip reasons must be reported per
OS. Synthetic CI does not represent Windows workstation or real-media acceptance.

This increment addresses Issue #7 only. It does not change the foundation
manifest, PR #6's transcript contract, existing tests/checkers/CI, or approved
license/status records. Correction uses a focused follow-up commit or reviewed
revert PR, never a shared reset, forced update, or automatic merge.
