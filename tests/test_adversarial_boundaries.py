from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

# The production runtime composes the canonical API first; importing a route module before
# that composition intentionally triggers its circular registration edge. Mirror the real
# import order so these tests probe runtime boundaries rather than an unsupported module order.
from audio_score_tool import api as _canonical_api  # noqa: F401
from audio_score_tool.api_token import ApiTokenMiddleware
from audio_score_tool.job_artifact_api_v2 import _managed_job_file
from audio_score_tool.omr import OMRImportError, normalize_musicxml
from audio_score_tool.upload_storage import UploadStorageError, persist_stream_atomic

VALID_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1"><measure number="1"><note><rest/><duration>1</duration></note></measure></part>
</score-partwise>
"""


def test_stream_limit_rejects_before_target_commit(tmp_path: Path):
    target = tmp_path / "source.bin"
    source = io.BytesIO(b"x" * 33)

    with pytest.raises(UploadStorageError) as exc:
        persist_stream_atomic(source, target, chunk_bytes=8, max_bytes=32)

    assert exc.value.status_code == 413
    assert not target.exists()
    assert not target.with_name(target.name + ".uploading").exists()


def test_stream_limit_accepts_exact_boundary(tmp_path: Path):
    target = tmp_path / "source.bin"
    payload = b"x" * 32
    written = persist_stream_atomic(io.BytesIO(payload), target, chunk_bytes=7, max_bytes=32)
    assert written == 32
    assert target.read_bytes() == payload


@pytest.mark.parametrize("chunk_bytes,max_bytes", [(0, None), (-1, None), (1, 0), (1, -5)])
def test_stream_limit_rejects_invalid_configuration(tmp_path: Path, chunk_bytes: int, max_bytes: int | None):
    with pytest.raises(ValueError):
        persist_stream_atomic(
            io.BytesIO(b"x"),
            tmp_path / "source.bin",
            chunk_bytes=chunk_bytes,
            max_bytes=max_bytes,
        )


def test_musicxml_rejects_declaration_hidden_after_large_prefix(tmp_path: Path):
    source = tmp_path / "late-doctype.musicxml"
    source.write_text(" " * 16_384 + "<!DOCTYPE score-partwise><score-partwise/>", encoding="utf-8")
    with pytest.raises(OMRImportError):
        normalize_musicxml(source, tmp_path / "normalized.musicxml")


def test_mxl_rejects_extreme_compression_ratio(tmp_path: Path):
    source = tmp_path / "bomb.mxl"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container><rootfiles><rootfile full-path="score.musicxml"/></rootfiles></container>',
        )
        archive.writestr("score.musicxml", VALID_XML + (" " * 2_000_000))

    with pytest.raises(OMRImportError):
        normalize_musicxml(source, tmp_path / "normalized.musicxml")


def test_managed_job_file_rejects_parent_and_symlink_escape(tmp_path: Path, monkeypatch):
    jobs = tmp_path / "jobs"
    root = jobs / "job-1"
    root.mkdir(parents=True)
    inside = root / "inside.txt"
    inside.write_text("ok", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    symlink = root / "escape.txt"
    try:
        symlink.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    monkeypatch.setattr("audio_score_tool.job_artifact_api_v2.jobs_dir", lambda: jobs)
    assert _managed_job_file("job-1", str(inside)) == inside.resolve()
    assert _managed_job_file("job-1", str(outside)) is None
    assert _managed_job_file("job-1", str(symlink)) is None


def test_api_token_rejects_duplicate_credentials(monkeypatch):
    async def api_read(_request):
        return JSONResponse({"ok": True})

    monkeypatch.setenv("AST_API_TOKEN", "secret-token")
    client = TestClient(ApiTokenMiddleware(Starlette(routes=[Route("/api/private", api_read)])))
    response = client.get(
        "/api/private",
        headers=[
            ("X-AudioScore-Token", "secret-token"),
            ("X-AudioScore-Token", "secret-token"),
        ],
    )
    assert response.status_code == 401
