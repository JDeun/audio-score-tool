"""Offline synthetic contracts for v1 frozen-sidecar managed feature acceptance.

No real third-party model/JRE/runtime is downloaded or uploaded by these tests.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import smoke_packaged_sidecar as smoke
from scripts import verify_packaged_managed_features as features
from scripts import verify_packaged_omr_pdf as real_omr
from scripts import verify_packaged_youtube_ingest as real_youtube

_BASE = "http://127.0.0.1:4567"
_TOKEN = "local-qa-acceptance-token"


def _midi(*, with_notes: bool = True) -> bytes:
    # Type-0 MIDI, one track, standard note-on/note-off/meta end events.
    track = (
        b"\x00\x90\x3c\x64\x81\x40\x80\x3c\x00"
        if with_notes else b""
    ) + b"\x00\xff\x2f\x00"
    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480) + b"MTrk" + struct.pack(">I", len(track)) + track


def _xml(*, with_notes=True) -> bytes:
    note = (
        "<note><pitch><step>C</step><octave>4</octave></pitch>"
        "<duration>1</duration><type>quarter</type></note>"
        if with_notes else "<note><rest/><duration>1</duration></note>"
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<score-partwise version="4.0"><part-list><score-part id="P1">'
        '<part-name>Piano</part-name></score-part></part-list>'
        f'<part id="P1"><measure number="1">{note}</measure></part>'
        '</score-partwise>'
    ).encode("utf-8")


def test_real_product_output_requires_nonempty_midi_note_ons_and_xml_parts():
    assert features._midi_note_count(_midi()) == 1
    assert features._musicxml_note_count(_xml()) == (1, 1)
    with pytest.raises(features.PackagedFeatureAcceptanceError, match="no note-on"):
        features._midi_note_count(_midi(with_notes=False))
    with pytest.raises(features.PackagedFeatureAcceptanceError, match="pitched"):
        features._musicxml_note_count(_xml(with_notes=False))


@pytest.mark.parametrize("payload", (
    b"", b"MThd", b"NOT-MIDI", b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480),
    b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480) + b"MTrk" + struct.pack(">I", 5) + b"\x00\x90",
    b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480) + b"MTrk" + struct.pack(">I", 5) + b"\x00\x90\x3c\x64\x80",
))
def test_malformed_midi_is_never_a_success(payload: bytes):
    with pytest.raises(features.PackagedFeatureAcceptanceError):
        features._midi_note_count(payload)


def test_running_status_and_meta_events_remain_valid():
    # Explicit first note-on, then running status for the second note.
    track = b"\x00\x90\x3c\x64\x00\x40\x50\x00\xff\x2f\x00"
    midi = b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480) + b"MTrk" + struct.pack(">I", len(track)) + track
    assert features._midi_note_count(midi) == 2


@pytest.mark.parametrize("payload", (
    b"", b"<html></html>",
    b'<!DOCTYPE score-partwise [<!ENTITY a "x">]><score-partwise/>',
    b'<score-partwise><part id="P1"><note></score-partwise>',
))
def test_bad_or_untrusted_musicxml_rejected(payload: bytes):
    with pytest.raises(features.PackagedFeatureAcceptanceError):
        features._musicxml_note_count(payload)


def test_engine_selection_uses_actual_packaged_api_and_validates_model(monkeypatch):
    calls = []
    def http(_base, token, method, route, **kwargs):
        assert token == _TOKEN and route == "/api/engines"
        calls.append((method, kwargs))
        if method == "GET":
            return 200, json.dumps({
                "packaged_runtime": True, "mt3_model": "yourmt3",
            }).encode()
        body = json.loads(kwargs["data"])
        assert body == {
            "usage_mode": "commercial",
            "transcription_engine": "mt3_infer",
            "mt3_model": "yourmt3",
        }
        assert kwargs["content_type"] == "application/json"
        return 200, json.dumps({
            "usage_mode": "commercial",
            "selected": "mt3_infer",
            "mt3_model": "yourmt3",
            "packaged_runtime": True,
            "preflight": {"ok": True},
        }).encode()
    monkeypatch.setattr(features, "_http", http)
    assert features._put_engine(_BASE, _TOKEN, None) == "yourmt3"
    assert [x[0] for x in calls] == ["GET", "PUT"]


def test_engine_selection_fails_closed_for_missing_model_or_preflight(monkeypatch):
    monkeypatch.setattr(features, "_http", lambda *a, **kw: (
        200, b'{"packaged_runtime":false, "mt3_model":"mr_mt3"}'
    ))
    with pytest.raises(features.PackagedFeatureAcceptanceError, match="frozen sidecar"):
        features._put_engine(_BASE, _TOKEN, None)
    monkeypatch.setattr(features, "_http", lambda *a, **kw: (
        (200, b'{"packaged_runtime":true,"mt3_model":"mr_mt3"}')
        if a[2] == "GET" else
        (200, b'{"packaged_runtime":true,"usage_mode":"commercial","mt3_model":"mr_mt3",'
              b'"selected":"mt3_infer","preflight":{"ok":false}}')
    ))
    with pytest.raises(features.PackagedFeatureAcceptanceError, match="not ready"):
        features._put_engine(_BASE, _TOKEN, None)
    with pytest.raises(features.PackagedFeatureAcceptanceError, match="model"):
        features._put_engine(_BASE, _TOKEN, "unsupported-model")


def test_packaged_wav_upload_uses_bounded_authenticated_multipart(tmp_path, monkeypatch):
    path = features.generate_fixture(tmp_path / "original-owned.wav")
    calls = []
    def http(base, token, method, route, **kwargs):
        calls.append((base, token, method, route, kwargs))
        assert method == "POST" and route == "/api/jobs"
        assert kwargs["data"].count(b"original-review.wav") == 1
        assert b'name="skip_lyrics"\r\n\r\ntrue' in kwargs["data"]
        assert kwargs["content_type"].startswith("multipart/form-data; boundary=")
        return 202, b'{"job_id":"aabbccddeeff00112233445566778899","status":"queued"}'
    monkeypatch.setattr(features, "_http", http)
    assert features._upload_owned_wav(_BASE, _TOKEN, path) == "aabbccddeeff00112233445566778899"
    assert len(calls) == 1
    assert path.is_file()


def test_job_polling_rejects_failed_and_late_jobs(monkeypatch):
    job_id = "a" * 32
    monkeypatch.setattr(features, "_http", lambda *a, **kw: (
        200, json.dumps({"job_id": job_id, "status": "failed", "error": "no model"}).encode()
    ))
    with pytest.raises(features.PackagedFeatureAcceptanceError, match="failed"):
        features._await_job(_BASE, _TOKEN, job_id, timeout_seconds=1)
    monkeypatch.setattr(features, "time", SimpleNamespace(monotonic=iter([10, 12]).__next__, sleep=lambda _: None))
    events = []
    monkeypatch.setattr(features, "_http", lambda *a, **kw: (
        events.append((a[2], a[3])) or (202, b'{"status":"cancelling"}')
    ))
    with pytest.raises(features.PackagedFeatureAcceptanceError, match="timed out"):
        features._await_job(_BASE, _TOKEN, job_id, timeout_seconds=1)
    assert events == [("POST", f"/api/jobs/{job_id}/cancel")]


def test_native_audiveris_launcher_and_jre_are_bound_to_owned_component(tmp_path, monkeypatch):
    root = tmp_path / "managed"
    installed = root / "installed" / "audiveris" / "v1"
    launcher = installed / "Audiveris.exe"
    java = installed / "runtime" / "bin" / "java.exe"
    release = installed / "runtime" / "release"
    for file in (launcher, java, release):
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"fixture-only")
    monkeypatch.setattr(features, "platform_key", lambda: "windows-x86_64")
    monkeypatch.setattr(features, "_find_runtime", lambda r, target: (launcher.resolve(), java.resolve(), release.resolve()))
    monkeypatch.setattr(features, "_http", lambda *a, **kw: (
        200, json.dumps({"ready": True, "command": str(launcher)}).encode(),
    ))
    calls = []
    def run(path, args, **kwargs):
        calls.append((path, args, kwargs))
        return SimpleNamespace(stdout="openjdk version 21.0.1")
    monkeypatch.setattr(features, "run_command", run)
    result = features._verify_packaged_omr_runtime(_BASE, _TOKEN, root, str(launcher))
    assert result["embedded_jre_started_without_system_path"] is True
    assert result["real_pdf_omr_accepted"] is False
    assert calls[0][0] == str(java)
    assert calls[0][1] == ["-version"]
    assert calls[0][2]["env"]["PATH"] == ""
    assert calls[0][2]["env"]["JAVA_HOME"] == ""


def test_packaged_audiveris_refuses_external_or_symlink_launchers(tmp_path, monkeypatch):
    root = tmp_path / "managed"
    root.mkdir()
    external = tmp_path / "external.exe"
    external.write_bytes(b"fixture-only")
    with pytest.raises(features.PackagedFeatureAcceptanceError, match="outside managed"):
        features._verify_packaged_omr_runtime(_BASE, _TOKEN, root, str(external))
    owned = root / "installed" / "audiveris" / "v1"
    owned.mkdir(parents=True)
    alias = owned / "Audiveris.exe"
    alias.symlink_to(external)
    with pytest.raises(features.PackagedFeatureAcceptanceError, match="linked"):
        features._verify_packaged_omr_runtime(_BASE, _TOKEN, root, str(alias))


def test_real_managed_audio_to_musicxml_downloads_from_packaged_api(tmp_path, monkeypatch):
    root = tmp_path / "managed"
    root.mkdir()
    components = []
    for component in ("transcription_engine", "youtube_runtime", "audiveris"):
        status = {"ready": True, "integrity": "verified"}
        if component == "audiveris":
            status["tools"] = {"audiveris": str(root / "launcher")}
        components.append({"key": component, "managed_status": status})
    job_id = "d" * 32
    requests = []
    def http(base, token, method, route, **_kwargs):
        requests.append((method, route))
        if route == "/api/setup/center":
            return 200, json.dumps({"components": components}).encode()
        if route.endswith("/files/midi"):
            return 200, _midi()
        if route.endswith("/files/musicxml"):
            return 200, _xml()
        raise AssertionError("Unexpected request " + route)
    monkeypatch.setattr(features, "_http", http)
    monkeypatch.setattr(features, "_verify_packaged_omr_runtime", lambda *_: {
        "api_managed_audiveris_launcher_verified": True,
        "embedded_jre_started_without_system_path": True,
        "real_pdf_omr_accepted": False,
    })
    monkeypatch.setattr(features, "_put_engine", lambda *_: "mr_mt3")
    monkeypatch.setattr(real_omr, "verify_real_pdf_omr", lambda *_a, **_kw: {
        "actual_pdf_omr_job_completed": True,
        "real_pdf_omr_accepted": True,
    })
    monkeypatch.setattr(real_youtube, "verify_packaged_youtube_ingest", lambda *_a, **_kw: {
        "real_managed_youtube_job_completed": True,
        "youtube_song_source_kind_persisted": True,
    })
    monkeypatch.setattr(features, "_upload_owned_wav", lambda *_: job_id)
    monkeypatch.setattr(features, "_await_job", lambda *_a, **_kw: {"job_id": job_id, "status": "done", "result": {"midi": "tmp", "musicxml": "tmp"}})
    output = features.verify_packaged_managed_features(
        _BASE, _TOKEN, root, private_workspace=tmp_path / "qa",
        youtube_review={"video_id": "AbC_dEfGh12", "source_url": "https://www.youtube.com/watch?v=AbC_dEfGh12"},
    )
    assert output["actual_product_audio_job_completed"] is True
    assert output["downloaded_midi_note_ons"] == 1
    assert output["downloaded_musicxml_pitched_notes"] == 1
    assert output["downloaded_musicxml_parts"] == 1
    assert output["real_pdf_omr_accepted"] is True
    assert output["actual_pdf_omr_job_completed"] is True
    assert output["real_managed_youtube_job_completed"] is True
    assert output["youtube_song_source_kind_persisted"] is True
    assert requests == [
        ("GET", "/api/setup/center"),
        ("GET", f"/api/jobs/{job_id}/files/midi"),
        ("GET", f"/api/jobs/{job_id}/files/musicxml"),
    ]


def test_packaged_feature_smoke_does_not_bypass_unapproved_component(tmp_path, monkeypatch):
    monkeypatch.setattr(features, "_http", lambda *args, **kw: (
        200, json.dumps({"components": [
            {"key": "transcription_engine", "managed_status": {"ready": False, "integrity": "not-installed"}},
        ]}).encode(),
    ))
    monkeypatch.setattr(
        features, "_put_engine",
        lambda *_a: (_ for _ in ()).throw(AssertionError("Not allowed to use incomplete runtime")),
    )
    with pytest.raises(features.PackagedFeatureAcceptanceError, match="transcription_engine"):
        features.verify_packaged_managed_features(
            _BASE, _TOKEN, tmp_path, private_workspace=tmp_path / "qa",
            youtube_review={"video_id": "AbC_dEfGh12", "source_url": "https://www.youtube.com/watch?v=AbC_dEfGh12"},
        )


def test_package_gate_uses_isolated_appdata_and_empty_host_path(monkeypatch, tmp_path):
    monkeypatch.setattr(smoke, "_sidecar", lambda: tmp_path / "fake-sidecar")
    monkeypatch.setattr(smoke, "_free_port", lambda: 4567)
    started = {}
    class Process:
        returncode = 0
        def poll(self): return None
        def terminate(self): return None
        def wait(self, timeout): return 0
    def popen(*_args, **kwargs):
        started["env"] = kwargs["env"]
        return Process()
    monkeypatch.setattr(smoke.subprocess, "Popen", popen)
    monkeypatch.setattr(smoke, "_request", lambda url, token=None: (
        (200, b'{"status":"ok"}') if token else (401, b'{}')
    ))
    monkeypatch.setattr(smoke, "_verify_embedded_runtime", lambda *_: None)
    monkeypatch.setattr(smoke, "_verify_managed_delivery", lambda *_: None)
    monkeypatch.setenv("AST_YOUTUBE_QA_RECEIPT_JSON", "operator-review-stub")
    monkeypatch.setattr(real_youtube, "reviewed_youtube_source", lambda raw: {
        "source_url": "https://www.youtube.com/watch?v=AbC_dEfGh12",
        "video_id": "AbC_dEfGh12", "rights_receipt_sha256": "a" * 64,
    } if raw == "operator-review-stub" else None)
    seen = {}
    monkeypatch.setattr(
        features, "verify_packaged_managed_features",
        lambda *args, **kwargs: (
            seen.update({"args": args, "kwargs": kwargs})
            or {
                "actual_product_audio_job_completed": True,
                "embedded_jre_started_without_system_path": True,
                "real_pdf_omr_accepted": True,
                "omr_musicxml_pdf_midi_parts_export_verified": True,
                "real_managed_youtube_job_completed": True,
                "youtube_song_source_kind_persisted": True,
            }
        ),
    )
    monkeypatch.setattr(sys, "argv", [
        "smoke_packaged_sidecar.py", "--require-managed-delivery",
        "--managed-mt3-model", "mr_mt3",
    ])
    smoke.main()
    env = started["env"]
    assert env["AST_PACKAGED"] == "1"
    assert env["PATH"] == ""
    assert "AST_YOUTUBE_QA_RECEIPT_JSON" not in env
    assert Path(env["AST_COMPONENT_DIR"]).name == "managed"
    assert Path(env["AST_DATA_DIR"]).name == "app-data"
    assert Path(env["AST_COMPONENT_DIR"]).parent == Path(env["AST_DATA_DIR"]).parent
    assert seen["kwargs"]["mt3_model"] == "mr_mt3"
    assert seen["args"][2] == Path(env["AST_COMPONENT_DIR"])


def test_model_override_requires_explicit_managed_delivery(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "smoke_packaged_sidecar.py", "--managed-mt3-model", "mr_mt3",
    ])
    with pytest.raises(SystemExit) as exc:
        smoke.main()
    assert exc.value.code == 2
