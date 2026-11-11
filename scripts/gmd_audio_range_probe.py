"""Read only bounded ranged ZIP members; evaluate raw drum AUDIO onsets.

Research-only, not a kick/snare recognizer for full-band music.
"""
from __future__ import annotations

import io
import math
import re
import urllib.request
import wave
import zipfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import PurePosixPath

import numpy as np

FULL_ZIP_URL = (
    "https://storage.googleapis.com/magentadata/datasets/groove/groove-v1.0.0.zip"
)
BUFFER_BYTES = 2 * 1024 * 1024
MAX_REQUEST_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 140 * 1024 * 1024
MAX_MEMBER_BYTES = 55 * 1024 * 1024
MAX_ARCHIVE_BYTES = 6 * 1024 * 1024 * 1024
ANALYZE_SECONDS = 12.0
TARGET_SR = 16000
ONSET_TOLERANCE_SECONDS = .05


class RangeNotSupported(ValueError):
    pass


class RangeZipReader:
    """Strict 206-only random access reader; never buffered full-file fallback."""

    def __init__(self, url=FULL_ZIP_URL):
        if url != FULL_ZIP_URL:
            raise ValueError("Only pinned public archive URL permitted")
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=25) as response:
            if response.status != 200:
                raise RangeNotSupported("No valid archive HEAD")
            self.size = int(response.headers.get("Content-Length", 0))
        if not 4_000_000_000 < self.size < MAX_ARCHIVE_BYTES:
            raise RangeNotSupported("Unexpected full archive size")
        self.url = url
        self.pos = 0
        self.cache = b""
        self.cache_start = 0
        self.bytes_fetched = 0
        self.requests_made = 0
        self.closed = False

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        if whence == 1:
            offset += self.pos
        elif whence == 2:
            offset += self.size
        elif whence != 0:
            raise ValueError("invalid seek type")
        if not 0 <= offset <= self.size:
            raise ValueError("out-of-bounds archive access")
        self.pos = offset
        return self.pos

    def _fetch(self, start, length):
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise RangeNotSupported("Disallowed range size")
        if self.bytes_fetched + length > MAX_TOTAL_BYTES:
            raise RangeNotSupported("Byte-budget exceeded")
        end = start + length - 1
        req = urllib.request.Request(
            self.url, headers={"Range": f"bytes={start}-{end}"}
        )
        with urllib.request.urlopen(req, timeout=45) as response:
            if response.status != 206:
                raise RangeNotSupported("Server ignored Range; refusing full ZIP")
            descriptor = response.headers.get("Content-Range", "")
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", descriptor)
            if not match or tuple(map(int, match.groups())) != (start, end, self.size):
                raise RangeNotSupported("Unexpected Content-Range")
            raw = response.read(length + 1)
            if len(raw) != length:
                raise RangeNotSupported("Incorrect ranged byte count")
        self.requests_made += 1
        self.bytes_fetched += len(raw)
        return raw

    def read(self, size=-1):
        if self.closed:
            raise ValueError("closed reader")
        if size is None or size < 0:
            size = self.size - self.pos
        if size > MAX_REQUEST_BYTES:
            raise RangeNotSupported("Oversized uncached read")
        size = min(size, self.size - self.pos)
        if size <= 0:
            return b""
        result = bytearray()
        while size:
            if not self.cache or not (
                self.cache_start <= self.pos < self.cache_start + len(self.cache)
            ):
                fetch_len = min(max(size, BUFFER_BYTES), MAX_REQUEST_BYTES,
                                self.size - self.pos)
                self.cache_start = self.pos
                self.cache = self._fetch(self.pos, fetch_len)
            index = self.pos - self.cache_start
            chunk = self.cache[index:index + size]
            if not chunk:
                raise RangeNotSupported("Cache failed to provide bytes")
            result.extend(chunk)
            self.pos += len(chunk)
            size -= len(chunk)
        return bytes(result)

    def close(self):
        self.closed = True
        self.cache = b""


def guarded_wav_member(remote_zip, name):
    if (name.startswith("/") or ".." in PurePosixPath(name).parts
            or not name.startswith("groove/") or not name.endswith(".wav")):
        raise ValueError("untrusted WAV name")
    info = remote_zip.getinfo(name)
    if (info.file_size < 1 or info.file_size > MAX_MEMBER_BYTES or
            info.compress_size > MAX_MEMBER_BYTES or info.flag_bits & 1):
        raise ValueError("WAV too large or encrypted")
    # Fixed chunks prevent a large unbounded ZipExtFile->remote read request.
    pieces, size = [], 0
    with remote_zip.open(info, "r") as stream:
        while True:
            chunk = stream.read(256 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_MEMBER_BYTES:
                raise ValueError("WAV decompression budget exceeded")
            pieces.append(chunk)
    raw = b"".join(pieces)
    if size != info.file_size:
        raise ValueError("WAV size mismatch")
    return raw, info.CRC, info.file_size


def decode_excerpt(raw, seconds=ANALYZE_SECONDS):
    import scipy.signal

    with wave.open(io.BytesIO(raw), "rb") as wav:
        channels, width, sr = (
            wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
        )
        if width != 2 or not 1 <= channels <= 2 or not 8000 <= sr <= 96000:
            raise ValueError("Unsupported WAV format")
        count = min(wav.getnframes(), round(seconds * sr))
        if count <= sr * 3:
            raise ValueError("WAV excerpt is too short")
        data = np.frombuffer(wav.readframes(count), dtype="<i2")
    mono = data.astype(np.float64).reshape(-1, channels).mean(axis=1) / 32768
    ratio = Fraction(TARGET_SR, sr).limit_denominator(1000)
    samples = scipy.signal.resample_poly(mono, ratio.numerator, ratio.denominator)
    return samples.astype(np.float32), len(mono) / sr, sr


def detect_audio_roles(samples, sr=TARGET_SR):
    """Frozen low-vs-high onset detector. No reference MIDI or BPM inputs."""
    nfft, hop = 1024, 160
    if len(samples) < nfft + hop or not np.isfinite(samples).all():
        raise ValueError("Invalid decoded wave")
    window = np.hanning(nfft)
    starts = np.arange(0, len(samples) - nfft, hop)
    frames = np.stack([samples[p:p+nfft] for p in starts])
    mag = np.abs(np.fft.rfft(frames * window, axis=1))
    freq = np.fft.rfftfreq(nfft, 1 / sr)
    novelty = np.maximum(0, mag[1:] - mag[:-1])
    low = novelty[:, (freq >= 45) & (freq <= 210)].sum(axis=1)
    high = novelty[:, (freq >= 400) & (freq <= 6000)].sum(axis=1)
    scaled = []
    for arr in (low, high):
        cap = max(float(np.percentile(arr, 99.0)), 1e-9)
        scaled.append(np.clip(arr / cap, 0, 1))
    low, high = scaled
    combined = np.maximum(low, high)
    floor = max(0.14, float(np.median(combined) + .45 *
                            (np.percentile(combined, 85) - np.median(combined))))
    peaks = []
    for i in range(1, len(combined) - 1):
        if (combined[i] < floor or combined[i] < combined[i-1]
                or combined[i] <= combined[i+1]):
            continue
        t = (starts[i + 1] + nfft / 2) / sr
        if peaks and t - peaks[-1][0] < .085:
            if combined[i] > peaks[-1][2]:
                peaks[-1] = (t, 'kick' if low[i] >= 1.25 * high[i]
                             else 'backbeat', float(combined[i]))
            continue
        peaks.append((t, 'kick' if low[i] >= 1.25 * high[i]
                      else 'backbeat', float(combined[i])))
    return peaks


def match_times(reference, predicted, tolerance=ONSET_TOLERANCE_SECONDS):
    """One-to-one, never-reference-corrected chronological onset evaluation."""
    ref, pred = sorted(reference), sorted(predicted)
    i = j = correct = 0
    while i < len(ref) and j < len(pred):
        diff = pred[j] - ref[i]
        if abs(diff) <= tolerance:
            correct += 1
            i += 1
            j += 1
        elif diff < 0:
            j += 1
        else:
            i += 1
    precision = correct / len(pred) if pred else 0.0
    recall = correct / len(ref) if ref else 0.0
    f1 = 2*precision*recall/(precision+recall) if precision+recall else 0.0
    return {"truth": len(ref), "predicted": len(pred), "matched": correct,
            "precision": precision, "recall": recall, "f1": f1}


def select_audio_rows(rows):
    """Predeclared metadata-only selection, no drum predictions or score truth."""
    selected = []
    for split, signature, kind, cap, max_duration in (
        ("test", "4-4", "beat", 2, 28),
        ("test", "4-4", "fill", 1, 15),
        ("validation", "3-4", "beat", 1, 165),
    ):
        matches = [
            r for r in rows if r["split"] == split
            and r["time_signature"] == signature
            and r["beat_type"] == kind
            and 4.0 <= float(r["duration"]) <= max_duration
        ]
        import hashlib

        chosen = sorted(matches, key=lambda r: hashlib.sha256(
            r["id"].encode()).hexdigest())[:cap]
        selected.extend(chosen)
    return selected
