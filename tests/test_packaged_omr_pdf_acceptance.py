"""Synthetic contracts for actual packaged PDF engraving → Audiveris OMR acceptance.

No copyrighted score, real Audiveris binary or model is included in CI.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

from scripts import smoke_packaged_sidecar as smoke
from scripts import verify_packaged_managed_features as features
from scripts import verify_packaged_omr_pdf as omr

_BASE = "http://127.0.0.1:4567"
_TOKEN = "test-owned-omr-token"
_IMPORT_ID = "a" * 32
_OMR_ID = "b" * 32


def _midi() -> bytes:
    track = b"\x00\x90\x3c\x64\x81\x40\x80\x3c\x00\x00\xff\x2f\x00"
    return (
        b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480)
        + b"MTrk" + struct.pack(">I", len(track)) + track
    )


def _musicxml(tmp_path: Path) -> bytes:
    from scripts.smoke_audiveris_omr_product_e2e import make_owned_musicxml

    path = tmp_path / "test-owned-score.musicxml"
    make_owned_musicxml(path)
    return path.read_bytes()


def test_original_score_upload_is_actual_authenticated_multipart(monkeypatch, tmp_path):
    xml_bytes = _musicxml(tmp_path)
    received = []

    def fake_http(base, token, method, route, **kwargs):
        received.append((base, token, method, route, kwargs))
        return 202, json.dumps({
            "job_id": _IMPORT_ID, "status": "queued", "kind": "notation-import",
        }).encode()

    monkeypatch.setattr(features, "_http", fake_http)
    job_id = omr._post_owned_file(
        _BASE, _TOKEN, route="/api/import/notation",
        filename="owned-original.musicxml", payload=xml_bytes,
        media_type="application/vnd.recordare.musicxml+xml", kind="notation-import",
    )
    assert job_id == _IMPORT_ID
    base, token, method, route, opts = received[0]
    assert (base, token, method, route) == (
        _BASE, _TOKEN, "POST", "/api/import/notation",
    )
    assert opts["content_type"].startswith("multipart/form-data; boundary=")
    assert b'name="file"; filename="owned-original.musicxml"' in opts["data"]
    assert xml_bytes in opts["data"]


@pytest.mark.parametrize("kind,payload,expected", (
    ("omr", b"NOT-PDF" * 200, "Rendered PDF"),
    ("notation-import", b'<!DOCTYPE xml><score-partwise/>' + b"x"*100, "unsafe XML"),
))
def test_uploaded_omr_fixture_rejects_unsafe_documents(
    monkeypatch, kind, payload, expected,
):
    monkeypatch.setattr(
        features, "_http",
        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("must not send")),
    )
    if kind == "omr":
        args = {
            "route": "/api/import/score", "filename": "owned-rendered-score.pdf",
            "media_type": "application/pdf",
        }
    else:
        args = {
            "route": "/api/import/notation", "filename": "owned-original.musicxml",
            "media_type": "application/vnd.recordare.musicxml+xml",
        }
    with pytest.raises(features.PackagedFeatureAcceptanceError, match=expected):
        omr._post_owned_file(_BASE, _TOKEN, payload=payload, kind=kind, **args)


def test_mismatched_job_kind_does_not_pass_pdf_ingress(monkeypatch):
    monkeypatch.setattr(features, "_http", lambda *_a, **_kw: (
        202, json.dumps({
            "job_id": _OMR_ID, "status": "queued", "kind": "notation-import",
        }).encode(),
    ))
    with pytest.raises(features.PackagedFeatureAcceptanceError, match="expected Job"):
        omr._post_owned_file(
            _BASE, _TOKEN, route="/api/import/score",
            filename="owned-rendered-score.pdf",
            payload=b"%PDF-" + b"x"*1200,
            media_type="application/pdf", kind="omr",
        )


def test_canonical_song_reconciliation_requires_one_correct_job(monkeypatch):
    monkeypatch.setattr(features, "_http", lambda *_a, **_kw: (
        200, json.dumps({"songs": [
            {"job_id": _OMR_ID, "song_id": _OMR_ID, "source_kind": "omr"},
            {"job_id": _IMPORT_ID, "song_id": _IMPORT_ID, "source_kind": "local"},
        ]}).encode(),
    ))
    assert omr._song_for_job(_BASE, _TOKEN, _OMR_ID, source="omr") == _OMR_ID
    with pytest.raises(features.PackagedFeatureAcceptanceError, match="exactly one"):
        omr._song_for_job(_BASE, _TOKEN, _OMR_ID, source="youtube")
    with pytest.raises(features.PackagedFeatureAcceptanceError, match="exactly one"):
        omr._song_for_job(_BASE, _TOKEN, "f"*32, source="omr")


def test_packaged_renderer_cannot_export_to_outside_qa_workspace(
    monkeypatch, tmp_path,
):
    outside = tmp_path / "foreign"
    outside.mkdir()
    monkeypatch.setattr(features, "_http", lambda *_a, **_kw: (
        200, json.dumps({"destination": str(outside)}).encode(),
    ))
    with pytest.raises(features.PackagedFeatureAcceptanceError, match="escaped"):
        omr._export_song(
            _BASE, _TOKEN, _IMPORT_ID,
            root=tmp_path / "owned-private", formats=["pdf"],
        )


def test_packaged_pdf_output_must_be_real_bounded_pdf_not_link(tmp_path):
    out = tmp_path / "published"
    out.mkdir()
    (out / "score.pdf").write_bytes(b"invalid" * 400)
    with pytest.raises(features.PackagedFeatureAcceptanceError, match="signature"):
        omr._read_generated_file(out, "score.pdf", b"%PDF-")
    (out / "score.pdf").unlink()
    foreign = tmp_path / "foreign.pdf"
    foreign.write_bytes(b"%PDF-" + b"a" * 1024)
    (out / "score.pdf").symlink_to(foreign)
    with pytest.raises(features.PackagedFeatureAcceptanceError, match="valid"):
        omr._read_generated_file(out, "score.pdf", b"%PDF-")


def test_complete_packaged_pdf_omr_to_canonical_song_and_exports(
    monkeypatch, tmp_path,
):
    original_xml = _musicxml(tmp_path)
    submission = []
    calls = []

    def fake_submit(base, token, *, route, filename, payload, media_type, kind):
        assert (base, token) == (_BASE, _TOKEN)
        assert (
            (route, kind) in {
                ("/api/import/notation", "notation-import"),
                ("/api/import/score", "omr"),
            }
        )
        if kind == "omr":
            assert payload.startswith(b"%PDF-")
            assert len(payload) > 1024
        else:
            assert payload == original_xml
        submission.append(kind)
        return _IMPORT_ID if kind == "notation-import" else _OMR_ID

    def completed_job(_base, _token, job_id, *, timeout_seconds):
        assert timeout_seconds <= 480
        return {
            "job_id": job_id, "status": "done",
            "kind": "omr" if job_id == _OMR_ID else "notation-import",
            "result": {"omr_provider": "audiveris"} if job_id == _OMR_ID
            else {"musicxml": "owned-source"},
        }

    def fake_http(base, token, method, route, **kwargs):
        calls.append((method, route))
        assert (base, token) == (_BASE, _TOKEN)
        if method == "GET" and route == "/api/songs":
            return 200, json.dumps({"songs": [
                {"job_id": _IMPORT_ID, "song_id": _IMPORT_ID, "source_kind": "local"},
                {"job_id": _OMR_ID, "song_id": _OMR_ID, "source_kind": "omr"},
            ]}).encode()
        if method == "GET" and route in {
            f"/api/jobs/{_OMR_ID}/files/musicxml",
            f"/api/songs/{_OMR_ID}/score",
        }:
            return 200, original_xml
        if method == "POST" and route in {
            f"/api/songs/{_IMPORT_ID}/export-to",
            f"/api/songs/{_OMR_ID}/export-to",
        }:
            message = json.loads(kwargs["data"])
            target = Path(message["destination_dir"]) / "verified-export"
            target.mkdir(parents=True)
            (target / "score.pdf").write_bytes(b"%PDF-" + b"x" * 1600)
            if "musicxml" in message["formats"]:
                (target / "score.musicxml").write_bytes(original_xml)
                (target / "score.mid").write_bytes(_midi())
                parts = target / "parts"
                parts.mkdir()
                (parts / "part-1.musicxml").write_bytes(original_xml)
                (parts / "part-1.pdf").write_bytes(b"%PDF-" + b"x" * 300)
            return 200, json.dumps({"destination": str(target)}).encode()
        raise AssertionError(f"Unexpected packaged HTTP call {method} {route}")

    monkeypatch.setattr(omr, "_post_owned_file", fake_submit)
    monkeypatch.setattr(features, "_await_job", completed_job)
    monkeypatch.setattr(features, "_http", fake_http)
    result = omr.verify_real_pdf_omr(
        _BASE, _TOKEN, workspace=tmp_path / "qa-private",
    )
    assert submission == ["notation-import", "omr"]
    assert result["real_pdf_omr_accepted"] is True
    assert result["actual_pdf_omr_job_completed"] is True
    assert result["recognized_omr_pitched_notes"] == 48
    assert result["canonical_song_reconciliation_verified"] is True
    assert result["omr_musicxml_pdf_midi_parts_export_verified"] is True
    assert result["omr_license_independently_approved"] is False
    assert ("POST", f"/api/songs/{_IMPORT_ID}/export-to") in calls
    assert ("POST", f"/api/songs/{_OMR_ID}/export-to") in calls


def test_recognizer_without_real_notes_does_not_pass_acceptance(monkeypatch, tmp_path):
    xml = (
        b'<?xml version="1.0"?>'
        b'<score-partwise><part-list><score-part id="P1">'
        b'<part-name>X</part-name></score-part></part-list>'
        b'<part id="P1"><measure number="1"><note><rest/>'
        b'<duration>1</duration></note></measure></part></score-partwise>'
    )
    monkeypatch.setattr(omr, "_post_owned_file", lambda *a, kind, **kw: (
        _IMPORT_ID if kind == "notation-import" else _OMR_ID
    ))
    monkeypatch.setattr(features, "_await_job", lambda *_a, **_kw: {
        "status": "done", "kind": "omr", "result": {"omr_provider": "audiveris"},
    })
    monkeypatch.setattr(omr, "_song_for_job", lambda *a, **kw: _IMPORT_ID)
    monkeypatch.setattr(omr, "_export_song", lambda *_a, **kw: (
        tmp_path / "pdf-exists"
    ))
    # Avoid faking a successful PDF - create a physically valid signature.
    pdf_dir = tmp_path / "pdf-exists"
    pdf_dir.mkdir()
    (pdf_dir / "score.pdf").write_bytes(b"%PDF-" + b"x" * 2000)
    monkeypatch.setattr(features, "_http", lambda *_a, **_kw: (200, xml))
    with pytest.raises(features.PackagedFeatureAcceptanceError, match="pitched"):
        omr.verify_real_pdf_omr(_BASE, _TOKEN, workspace=tmp_path / "qa-private")


def test_omr_timeout_policy_never_accepts_unbounded_wait(tmp_path):
    with pytest.raises(features.PackagedFeatureAcceptanceError, match="eight minutes"):
        omr.verify_real_pdf_omr(
            _BASE, _TOKEN, workspace=tmp_path, timeout_seconds=481,
        )


def test_release_gate_explicitly_requires_real_pdf_omr_and_all_exports():
    source = Path(smoke.__file__).read_text(encoding="utf-8")
    assert 'result.get("real_pdf_omr_accepted") is not True' in source
    assert 'result.get("omr_musicxml_pdf_midi_parts_export_verified") is not True' in source
    assert "scripts.verify_packaged_omr_pdf" in Path(
        features.__file__
    ).read_text(encoding="utf-8")
