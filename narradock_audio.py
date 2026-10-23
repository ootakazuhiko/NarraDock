"""Measure a bounded PCM WAV through the selected asset's verified byte stream."""
from __future__ import annotations

from pathlib import Path
import struct
from typing import Any

from narradock_assets import AssetError, copy_verified_asset
from narradock_candidates import CandidateError, candidate_fingerprint, snapshot_candidate

SCHEMA_VERSION = "pcm-wav-measurements-0.1"
MAX_WAV_BYTES = 1024 * 1024 * 1024
MAX_CAPTURE_BYTES = 32 * 1024 * 1024
MAX_METADATA_BYTES = 1024 * 1024
MAX_CHUNKS = 128


class AudioMeasurementError(ValueError):
    """A fixed diagnostic without source paths, metadata or sample data."""


class _PcmWav:
    """Private tentative sink; no result is valid until the source verifier returns."""

    def __init__(self, expected_size: int, *, capture: bool = False):
        self.expected_size = expected_size
        self.position = 0
        self.state = "riff"
        self.needed = 12
        self.buffer = bytearray()
        self.remaining = 0
        self.padding = 0
        self.chunks = 0
        self.metadata_bytes = 0
        self.have_format = False
        self.have_data = False
        self.channels = self.rate = self.align = 0
        self.frames = self.zero_frames = 0
        self.peaks: list[int] = []
        self.endpoints: list[int] = []
        self.tail = b""
        self.captured = bytearray() if capture else None

    def _fixed(self, state: str, needed: int) -> None:
        self.state, self.needed = state, needed

    def _end_chunk(self) -> None:
        if self.tail:
            raise AudioMeasurementError("Incomplete PCM frame")
        if self.padding:
            self._fixed("pad", 1)
        else:
            self._fixed("chunk", 8)

    def _header(self, raw: bytes) -> None:
        if self.state == "riff":
            magic, size, kind = struct.unpack("<4sI4s", raw)
            if magic != b"RIFF" or kind != b"WAVE" or size + 8 != self.expected_size:
                raise AudioMeasurementError("Invalid RIFF envelope")
            self._fixed("chunk", 8)
        elif self.state == "chunk":
            kind, size = struct.unpack("<4sI", raw)
            self.chunks += 1
            self.padding = size % 2
            self.remaining = size
            if (self.chunks > MAX_CHUNKS
                    or size + self.padding > self.expected_size - self.position):
                raise AudioMeasurementError("Invalid WAV chunk extent")
            if kind == b"fmt ":
                if self.have_format or self.have_data or size != 16:
                    raise AudioMeasurementError("Unsupported WAV format chunk")
                self._fixed("fmt", 16)
            elif kind == b"data":
                if not self.have_format or self.have_data or not size or size % self.align:
                    raise AudioMeasurementError("Invalid PCM data chunk")
                self.have_data = True
                self.state = "data"
            elif kind in {b"JUNK", b"LIST"}:
                self.metadata_bytes += size
                if self.metadata_bytes > MAX_METADATA_BYTES:
                    raise AudioMeasurementError("WAV metadata exceeds limit")
                if kind == b"LIST":
                    if size < 4:
                        raise AudioMeasurementError("Unsupported WAV list")
                    self._fixed("list", 4)
                elif size:
                    self.state = "skip"
                else:
                    self._end_chunk()
            else:
                raise AudioMeasurementError("Unsupported WAV chunk")
        elif self.state == "fmt":
            tag, channels, rate, byte_rate, align, bits = struct.unpack("<HHIIHH", raw)
            if (tag != 1 or channels not in {1, 2} or bits != 16
                    or not 8000 <= rate <= 192000 or align != channels * 2
                    or byte_rate != rate * align):
                raise AudioMeasurementError("Unsupported PCM format")
            self.channels, self.rate, self.align = channels, rate, align
            self.peaks, self.endpoints = [0] * channels, [0] * channels
            self.have_format = True
            self._end_chunk()
        elif self.state == "list":
            if raw != b"INFO":
                raise AudioMeasurementError("Unsupported WAV list")
            self.remaining -= 4
            if self.remaining:
                self.state = "skip"
            else:
                self._end_chunk()
        else:  # A mandatory RIFF pad byte has no semantic value.
            self._fixed("chunk", 8)

    def _samples(self, block: memoryview) -> None:
        # Only one bounded verifier block and an incomplete frame are retained.
        payload = self.tail + block.tobytes()
        end = len(payload) - len(payload) % self.align
        self.tail = payload[end:]
        for frame in struct.iter_unpack("<h" if self.channels == 1 else "<hh", payload[:end]):
            self.frames += 1
            if not any(frame):
                self.zero_frames += 1
            for channel, sample in enumerate(frame):
                self.peaks[channel] = max(self.peaks[channel], abs(sample))
                if sample in {-32768, 32767}:
                    self.endpoints[channel] += 1

    def write(self, data: bytes) -> int:
        if len(data) > self.expected_size - self.position:
            raise AudioMeasurementError("WAV exceeds selected size")
        block = memoryview(data)
        while block:
            if self.state in {"data", "skip"}:
                size = min(len(block), self.remaining)
                if self.state == "data":
                    self._samples(block[:size])
                self.remaining -= size
                self.position += size
                block = block[size:]
                if not self.remaining:
                    self._end_chunk()
            else:
                size = min(len(block), self.needed - len(self.buffer))
                self.buffer.extend(block[:size])
                self.position += size
                block = block[size:]
                if len(self.buffer) == self.needed:
                    header = bytes(self.buffer)
                    self.buffer.clear()
                    self._header(header)
        if self.captured is not None:
            self.captured.extend(data)
        return len(data)

    def finish(self) -> None:
        if (self.position != self.expected_size or self.state != "chunk" or self.buffer
                or not self.have_format or not self.have_data or self.tail):
            raise AudioMeasurementError("Incomplete WAV stream")


def measure_candidate_wav(document: Any, *, project_id: str, expected_fingerprint: str,
                          registry: Any, project_root: Path) -> dict[str, Any]:
    """Return candidate-bound PCM observations, never a QA or permission decision.

    Inputs and the trusted root follow the asset/candidate APIs. Unsupported or
    unverifiable input raises AudioMeasurementError; a measured duration mismatch
    is a finding in a successful observation. No output file is created.
    """
    return _consume_candidate_wav(document, project_id=project_id,
        expected_fingerprint=expected_fingerprint, registry=registry,
        project_root=project_root, capture=False)[1]


def read_candidate_wav(document: Any, *, project_id: str, expected_fingerprint: str,
                       registry: Any, project_root: Path) -> tuple[bytes, dict[str, Any]]:
    """Return at most 32 MiB of verified WAV bytes and measurements of those reads.

    Nothing is returned until source guards, candidate comparison and parsing
    finish. The caller owns this private copy, including any embedded metadata.
    No file is written. A duration mismatch remains a measurement finding.
    """
    return _consume_candidate_wav(document, project_id=project_id,
        expected_fingerprint=expected_fingerprint, registry=registry,
        project_root=project_root, capture=True)


def _consume_candidate_wav(document: Any, *, project_id: str, expected_fingerprint: str,
                           registry: Any, project_root: Path,
                           capture: bool) -> tuple[bytes, dict[str, Any]]:
    try:
        candidate = snapshot_candidate(document, project_id=project_id)
        revision = candidate_fingerprint(candidate, project_id=project_id)
        if type(expected_fingerprint) is not str or expected_fingerprint != revision:
            raise AudioMeasurementError("Candidate fingerprint mismatch")
        audio = candidate["audio"]
        limit = MAX_CAPTURE_BYTES if capture else MAX_WAV_BYTES
        if not 46 <= audio["size_bytes"] <= limit:
            raise AudioMeasurementError("Unsupported WAV size")
        parser = _PcmWav(audio["size_bytes"], capture=capture)
        verified = copy_verified_asset(registry, project_root=project_root,
            project_id=candidate["project_id"], asset_id=audio["asset_id"], destination=parser)
        if verified["size_bytes"] != audio["size_bytes"] or verified["sha256"] != audio["sha256"]:
            raise AudioMeasurementError("Candidate asset declaration mismatch")
        parser.finish()
    except (AssetError, CandidateError, AudioMeasurementError):
        raise AudioMeasurementError("Candidate PCM WAV could not be measured") from None

    # Exact frame time is retained; integer milliseconds use nearest, half up.
    rounded_ms = (2 * parser.frames * 1000 + parser.rate) // (2 * parser.rate)
    declared_ms = audio.get("duration_ms")
    matches = None if declared_ms is None else rounded_ms == declared_ms
    receipt = {"schema_version": SCHEMA_VERSION, "measured": True, "bytes_verified": True,
            "scope": "candidate_pcm_wav_measurements_only", "candidate_fingerprint": revision,
            "project_id": candidate["project_id"], "content_id": candidate["content_id"],
            "audio": {"asset_id": audio["asset_id"], "size_bytes": verified["size_bytes"],
                      "sha256": verified["sha256"]},
            "pcm": {"format": "signed-16-le", "channels": parser.channels,
                    "sample_rate_hz": parser.rate, "frame_count": parser.frames,
                    "sample_peak_abs": parser.peaks, "full_scale_sample_count": parser.endpoints,
                    "zero_frame_count": parser.zero_frames},
            "duration": {"milliseconds_numerator": parser.frames * 1000,
                         "milliseconds_denominator": parser.rate, "rounded_ms": rounded_ms,
                         "rounding": "nearest_ms_half_up", "declared_ms": declared_ms,
                         "matches_declared": matches},
            "findings": ["duration_mismatch"] if matches is False else [],
            "rights_verified": False, "media_qa_passed": False, "human_reviewed": False,
            "transcript_alignment_verified": False, "packaged": False,
            "external_transfer": False, "publication": False}
    return bytes(parser.captured) if parser.captured is not None else b"", receipt
