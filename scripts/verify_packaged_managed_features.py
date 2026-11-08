"""Optional v1 acceptance: REAL managed audio→score via the frozen sidecar API.

Run only after the same packaged sidecar has downloaded and installed the
reviewed Windows/macOS managed AMT, YouTube and Audiveris runtimes. An original
locally generated WAV is uploaded through the *packaged* HTTP API, not passed to
a host-Python model. The verified native model must emit nonempty MIDI and
MusicXML before a release candidate can pass.

No system PATH fallback, model auto-download, copyrighted input, external URL,
license grant, public artifact or complete clean-machine installer claim.
"""
from __future__ import annotations

import json
import re
import struct
import time
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from audio_score_tool.managed_component_catalog import platform_key
from audio_score_tool.runner import CommandError, run_command
from scripts.generate_tier2_smoke_audio import generate_fixture
from scripts.verify_audiveris_native_layout import AudiverisReviewError, _find_runtime

_MAX_RESPONSE = 16 * 1024 * 1024
_MODEL_CHOICES = {"mr_mt3", "yourmt3"}
_JOB_ID = re.compile(r"[a-f0-9]{32}\Z")


class PackagedFeatureAcceptanceError(RuntimeError):
    """A downloaded and installed runtime cannot actually serve the product."""


def _http(
    base_url: str, token: str, method: str, route: str, *,
    data: bytes | None = None, content_type: str | None = None,
    timeout: int = 30,
) -> tuple[int, bytes]:
    if not re.fullmatch(r"http://127\.0\.0\.1:[1-9][0-9]{0,4}", base_url):
        raise PackagedFeatureAcceptanceError("Only the loopback packaged API may be tested")
    if not route.startswith("/api/") or "?" in route or "//" in route:
        raise PackagedFeatureAcceptanceError("Packaged acceptance route must be fixed and local")
    headers = {"X-AudioScore-Token": token}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(
        base_url + route, data=data, headers=headers, method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            payload = response.read(_MAX_RESPONSE + 1)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        payload = exc.read(_MAX_RESPONSE + 1)
    if len(payload) > _MAX_RESPONSE:
        raise PackagedFeatureAcceptanceError("Packaged API response exceeded the safe size")
    return status, payload


def _json_ok(status: int, payload: bytes, *, name: str, expected: int = 200) -> dict:
    if status != expected:
        raise PackagedFeatureAcceptanceError(
            f"{name} returned HTTP {status}, expected {expected}: "
            + payload[:200].decode("utf-8", "replace")
        )
    try:
        result = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackagedFeatureAcceptanceError(f"{name} returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise PackagedFeatureAcceptanceError(f"{name} did not return an object")
    return result


def _put_engine(base: str, token: str, model_override: str | None) -> str:
    """Configure the QA-only, isolated settings store through the real API."""
    status, data = _http(base, token, "GET", "/api/engines")
    initial = _json_ok(status, data, name="packaged engines")
    if initial.get("packaged_runtime") is not True:
        raise PackagedFeatureAcceptanceError("Transcription API is not using the frozen sidecar")
    model = model_override if model_override is not None else initial.get("mt3_model")
    if not isinstance(model, str) or model not in _MODEL_CHOICES:
        raise PackagedFeatureAcceptanceError("No approved-for-review MT3 model was selected")
    body = json.dumps({
        "usage_mode": "commercial",
        "transcription_engine": "mt3_infer",
        "mt3_model": model,
    }).encode("utf-8")
    status, data = _http(
        base, token, "PUT", "/api/engines",
        data=body, content_type="application/json",
    )
    actual = _json_ok(status, data, name="packaged engine selection")
    if (
        actual.get("selected") != "mt3_infer"
        or actual.get("mt3_model") != model
        or actual.get("usage_mode") != "commercial"
        or actual.get("packaged_runtime") is not True
    ):
        raise PackagedFeatureAcceptanceError("Packaged engine selection was not persisted")
    readiness = actual.get("preflight")
    if not isinstance(readiness, dict) or readiness.get("ok") is not True:
        raise PackagedFeatureAcceptanceError(
            "Installed native MT3 runtime/model is not ready in the packaged product"
        )
    return model


def _upload_owned_wav(base: str, token: str, fixture: Path) -> str:
    if fixture.is_symlink() or not fixture.is_file() or not 300_000 <= fixture.stat().st_size <= 2_000_000:
        raise PackagedFeatureAcceptanceError("Original transcription WAV was not generated safely")
    raw = fixture.read_bytes()
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise PackagedFeatureAcceptanceError("Generated original fixture is not WAV")
    boundary = "ast-inference-" + uuid.uuid4().hex
    framing = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="original-review.wav"\r\n'
        "Content-Type: audio/wav\r\n\r\n"
    ).encode("ascii")
    ending = (
        f"\r\n--{boundary}\r\n"
        'Content-Disposition: form-data; name="skip_lyrics"\r\n\r\ntrue'
        f"\r\n--{boundary}--\r\n"
    ).encode("ascii")
    status, response = _http(
        base, token, "POST", "/api/jobs",
        data=framing + raw + ending,
        content_type=f"multipart/form-data; boundary={boundary}",
        timeout=60,
    )
    result = _json_ok(status, response, name="packaged WAV upload", expected=202)
    job_id = result.get("job_id")
    if not isinstance(job_id, str) or _JOB_ID.fullmatch(job_id) is None:
        raise PackagedFeatureAcceptanceError("Packaged upload did not return a valid Job ID")
    if result.get("status") != "queued":
        raise PackagedFeatureAcceptanceError("Transcription Job was not queued")
    return job_id


def _await_job(base: str, token: str, job_id: str, *, timeout_seconds: float = 1200) -> dict:
    """Only terminal success counts, with a bounded attempt to cancel on timeout."""
    if _JOB_ID.fullmatch(job_id) is None:
        raise PackagedFeatureAcceptanceError("An invalid Job ID cannot be polled")
    if timeout_seconds <= 0 or timeout_seconds > 1800:
        raise PackagedFeatureAcceptanceError("Packaged QA Job timeout must be bounded")
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status, raw = _http(base, token, "GET", f"/api/jobs/{job_id}")
        job = _json_ok(status, raw, name="packaged transcription Job")
        if job.get("job_id") != job_id:
            raise PackagedFeatureAcceptanceError("Transcription Job identity changed")
        state = job.get("status")
        if state == "done":
            if not isinstance(job.get("result"), dict):
                raise PackagedFeatureAcceptanceError("Finished Job has no result payload")
            return job
        if state in {"failed", "cancelled"}:
            error = str(job.get("error") or "unknown")[-350:]
            raise PackagedFeatureAcceptanceError(f"Packaged transcription Job {state}: {error}")
        if state not in {"queued", "running", "cancelling"}:
            raise PackagedFeatureAcceptanceError(f"Unexpected transcription Job state: {state}")
        time.sleep(2)
    _http(base, token, "POST", f"/api/jobs/{job_id}/cancel", data=b"", timeout=10)
    raise PackagedFeatureAcceptanceError("Packaged real-model transcription timed out")


def _vlq(data: bytes, cursor: int, end: int) -> tuple[int, int]:
    result = 0
    for _ in range(4):
        if cursor >= end:
            raise PackagedFeatureAcceptanceError("Truncated MIDI variable-length quantity")
        byte = data[cursor]
        cursor += 1
        result = (result << 7) | (byte & 0x7F)
        if byte & 0x80 == 0:
            return result, cursor
    raise PackagedFeatureAcceptanceError("Malformed MIDI variable-length quantity")


def _midi_note_count(payload: bytes) -> int:
    """Count actual MIDI note-on events with bounded track/running-status parsing."""
    if len(payload) < 22 or len(payload) > _MAX_RESPONSE or payload[:4] != b"MThd":
        raise PackagedFeatureAcceptanceError("Packaged AMT did not emit a MIDI file")
    header_bytes = int.from_bytes(payload[4:8], "big")
    if header_bytes < 6 or header_bytes > 128 or len(payload) < 8 + header_bytes:
        raise PackagedFeatureAcceptanceError("Packaged MIDI header is invalid")
    format_type, ntracks, _division = struct.unpack_from(">HHH", payload, 8)
    if format_type not in {0, 1, 2} or not 1 <= ntracks <= 256:
        raise PackagedFeatureAcceptanceError("Packaged MIDI has no valid tracks")
    pos = 8 + header_bytes
    notes = 0
    for _ in range(ntracks):
        if payload[pos:pos + 4] != b"MTrk" or pos + 8 > len(payload):
            raise PackagedFeatureAcceptanceError("Packaged MIDI track header is missing")
        track_bytes = int.from_bytes(payload[pos + 4:pos + 8], "big")
        pos += 8
        end = pos + track_bytes
        if end > len(payload):
            raise PackagedFeatureAcceptanceError("Packaged MIDI track overruns its file")
        running: int | None = None
        while pos < end:
            _, pos = _vlq(payload, pos, end)
            if pos >= end:
                raise PackagedFeatureAcceptanceError("Packaged MIDI event is truncated")
            if payload[pos] & 0x80:
                status = payload[pos]
                pos += 1
                if 0x80 <= status <= 0xEF:
                    running = status
                else:
                    running = None
            elif running is not None:
                status = running
            else:
                raise PackagedFeatureAcceptanceError("MIDI running status is invalid")
            if status == 0xFF:
                if pos >= end:
                    raise PackagedFeatureAcceptanceError("MIDI meta event is incomplete")
                pos += 1
                length, pos = _vlq(payload, pos, end)
                pos += length
            elif status in {0xF0, 0xF7}:
                length, pos = _vlq(payload, pos, end)
                pos += length
            elif 0x80 <= status <= 0xEF:
                data_bytes = 1 if status & 0xF0 in {0xC0, 0xD0} else 2
                if pos + data_bytes > end:
                    raise PackagedFeatureAcceptanceError("MIDI channel event is incomplete")
                if (status & 0xF0) == 0x90 and payload[pos + 1] > 0:
                    notes += 1
                pos += data_bytes
            else:
                raise PackagedFeatureAcceptanceError("MIDI system message is unexpected")
            if pos > end:
                raise PackagedFeatureAcceptanceError("Packaged MIDI event overruns track")
    if pos != len(payload) or notes < 1:
        raise PackagedFeatureAcceptanceError("Packaged MIDI has no note-on events or trailing bytes")
    return notes


def _musicxml_note_count(payload: bytes) -> tuple[int, int]:
    if len(payload) < 100 or len(payload) > _MAX_RESPONSE or b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise PackagedFeatureAcceptanceError("Packaged MusicXML is empty, unsafe or too large")
    try:
        score = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise PackagedFeatureAcceptanceError("Packaged MusicXML cannot be parsed") from exc
    if score.tag.split("}")[-1] not in {"score-partwise", "score-timewise"}:
        raise PackagedFeatureAcceptanceError("Packaged output is not a MusicXML score")
    parts = score.findall(".//{*}part")
    notes = sum(
        note.find("{*}pitch") is not None
        for part in parts for note in part.findall(".//{*}note")
    )
    if not parts or notes < 1:
        raise PackagedFeatureAcceptanceError("Packaged MusicXML score has no pitched notes/parts")
    return notes, len(parts)


def _verify_packaged_omr_runtime(
    base: str, token: str, managed_root: Path, launcher_path: str,
) -> dict[str, bool]:
    """Verify *installed* Audiveris launcher and its bundled JRE, no PATH Java."""
    root = managed_root.resolve()
    launcher = Path(launcher_path)
    if launcher.is_symlink() or not launcher.is_file() or not launcher.is_absolute():
        raise PackagedFeatureAcceptanceError("Installed Audiveris launcher is missing or linked")
    try:
        parts = launcher.resolve().relative_to(root).parts
    except ValueError as exc:
        raise PackagedFeatureAcceptanceError("Audiveris launcher is outside managed storage") from exc
    if len(parts) < 4 or parts[:2] != ("installed", "audiveris"):
        raise PackagedFeatureAcceptanceError("Audiveris launcher does not belong to its managed owner")
    component_dir = root.joinpath(*parts[:3])
    # The product path must not traverse a symlinked parent.
    ancestor = launcher.parent
    while ancestor.is_relative_to(root) and ancestor != root:
        if ancestor.is_symlink():
            raise PackagedFeatureAcceptanceError("Managed Audiveris parent contains a symlink")
        ancestor = ancestor.parent
    try:
        native_launcher, java, release = _find_runtime(component_dir, platform_key())
    except AudiverisReviewError as exc:
        raise PackagedFeatureAcceptanceError("Audiveris/JRE native layout is invalid") from exc
    if native_launcher != launcher.resolve() or not release.is_file():
        raise PackagedFeatureAcceptanceError("Audiveris managed launcher/JRE identity differs")
    status, raw = _http(base, token, "GET", "/api/omr/status")
    response = _json_ok(status, raw, name="packaged OMR status")
    if response.get("ready") is not True or Path(str(response.get("command"))).resolve() != native_launcher:
        raise PackagedFeatureAcceptanceError("Packaged OMR API is not wired to its managed launcher")
    try:
        output = run_command(
            str(java),
            ["-version"],
            env={"PATH": "", "JAVA_HOME": "", "PYTHONNOUSERSITE": "1"},
            timeout_seconds=45,
            max_output_bytes=16 * 1024,
        ).stdout.lower()
    except CommandError as exc:
        raise PackagedFeatureAcceptanceError("Embedded Audiveris JRE failed native startup") from exc
    if "version" not in output and "openjdk" not in output:
        raise PackagedFeatureAcceptanceError("Embedded Audiveris JRE did not report its runtime")
    return {
        "api_managed_audiveris_launcher_verified": True,
        "embedded_jre_started_without_system_path": True,
        "real_pdf_omr_accepted": False,  # separate actual OMR acceptance is required
    }


def verify_packaged_managed_features(
    base_url: str, token: str, managed_root: Path, *,
    private_workspace: Path,
    mt3_model: str | None = None,
    job_timeout_seconds: float = 1200,
) -> dict[str, Any]:
    """Real uploaded audio→managed frozen CLI→MIDI→MusicXML, plus JRE startup."""
    status, payload = _http(base_url, token, "GET", "/api/setup/center")
    setup = _json_ok(status, payload, name="packaged managed component state")
    items = setup.get("components")
    if not isinstance(items, list):
        raise PackagedFeatureAcceptanceError("Packaged Setup Center has no components")
    components = {item.get("key"): item for item in items if isinstance(item, dict)}
    for component in ("transcription_engine", "youtube_runtime", "audiveris"):
        info = components.get(component)
        managed = info.get("managed_status") if isinstance(info, dict) else None
        if (
            not isinstance(managed, dict)
            or managed.get("ready") is not True
            or managed.get("integrity") != "verified"
        ):
            raise PackagedFeatureAcceptanceError(f"{component}: not verified after managed installation")
    audiveris_tools = components["audiveris"]["managed_status"].get("tools")
    if not isinstance(audiveris_tools, dict) or not isinstance(audiveris_tools.get("audiveris"), str):
        raise PackagedFeatureAcceptanceError("Audiveris installer did not register a launcher")
    omr = _verify_packaged_omr_runtime(base_url, token, managed_root, audiveris_tools["audiveris"])

    model = _put_engine(base_url, token, mt3_model)
    private_workspace.mkdir(parents=True, exist_ok=True)
    fixture = generate_fixture(private_workspace / "original-owned-polyphonic.wav")
    job_id = _upload_owned_wav(base_url, token, fixture)
    _await_job(base_url, token, job_id, timeout_seconds=job_timeout_seconds)

    status, midi_bytes = _http(base_url, token, "GET", f"/api/jobs/{job_id}/files/midi")
    if status != 200:
        raise PackagedFeatureAcceptanceError(f"Packaged MIDI download failed: HTTP {status}")
    midi_notes = _midi_note_count(midi_bytes)
    status, xml_bytes = _http(base_url, token, "GET", f"/api/jobs/{job_id}/files/musicxml")
    if status != 200:
        raise PackagedFeatureAcceptanceError(f"Packaged MusicXML download failed: HTTP {status}")
    notes, parts = _musicxml_note_count(xml_bytes)
    return {
        "schema_version": "1",
        "mt3_model": model,
        "actual_product_audio_job_completed": True,
        "downloaded_midi_note_ons": midi_notes,
        "downloaded_musicxml_pitched_notes": notes,
        "downloaded_musicxml_parts": parts,
        "packaged_backend_http_job_api_verified": True,
        "system_python_required_for_model_execution": False,
        **omr,
        "clean_machine_desktop_installer_verified": False,
        "model_redistribution_approved": False,
        "publication_status": "already-approved-catalog-only",
    }
