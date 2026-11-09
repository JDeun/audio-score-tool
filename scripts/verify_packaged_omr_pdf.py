"""Real PDF OMR acceptance against the same approved frozen product sidecar.

An owned 12-bar MusicXML fixture is imported, engraved via the frozen
Verovio/fpdf2 backend, recognized by the installed Audiveris+JRE, imported to
the canonical SQLite Song library, and exported to MusicXML/PDF/MIDI/parts.

No host Python PDF renderer, model download, external source score or fake
recognizer is involved in the opt-in manual v1-release acceptance.
"""
from __future__ import annotations

import hashlib
import json
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from scripts import verify_packaged_managed_features as accepted

_PDF_LIMIT = 16 * 1024 * 1024
_MIN_RECOGNIZED_NOTES = 4


def _post_owned_file(
    base: str, token: str, *, route: str, filename: str,
    payload: bytes, media_type: str, kind: str,
) -> str:
    if (
        (route, filename, kind) not in {
            ("/api/import/notation", "owned-original.musicxml", "notation-import"),
            ("/api/import/score", "owned-rendered-score.pdf", "omr"),
        }
        or not 100 <= len(payload) <= _PDF_LIMIT
    ):
        raise accepted.PackagedFeatureAcceptanceError("Invalid original OMR fixture upload")
    if filename.endswith(".pdf"):
        if not payload.startswith(b"%PDF-") or len(payload) < 1024:
            raise accepted.PackagedFeatureAcceptanceError("Rendered PDF is empty or malformed")
    elif (
        b"<!DOCTYPE" in payload.upper()
        or b"<!ENTITY" in payload.upper()
    ):
        raise accepted.PackagedFeatureAcceptanceError("Original fixture has unsafe XML declarations")

    boundary = "ast-omr-" + uuid.uuid4().hex
    prefix = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {media_type}\r\n\r\n"
    ).encode("ascii")
    suffix = f"\r\n--{boundary}--\r\n".encode("ascii")
    code, raw = accepted._http(
        base, token, "POST", route,
        data=prefix + payload + suffix,
        content_type=f"multipart/form-data; boundary={boundary}",
        timeout=60,
    )
    result = accepted._json_ok(code, raw, name=f"packaged {kind}", expected=202)
    job_id = result.get("job_id")
    if (
        not isinstance(job_id, str) or accepted._JOB_ID.fullmatch(job_id) is None
        or result.get("status") != "queued" or result.get("kind") != kind
    ):
        raise accepted.PackagedFeatureAcceptanceError("Packaged OMR fixture did not queue expected Job")
    return job_id


def _song_for_job(base: str, token: str, job_id: str, *, source: str | None = None) -> str:
    """Use the real Song library to trigger completed Job reconciliation."""
    code, raw = accepted._http(base, token, "GET", "/api/songs")
    songs = accepted._json_ok(code, raw, name="packaged Song library").get("songs")
    if not isinstance(songs, list):
        raise accepted.PackagedFeatureAcceptanceError("Packaged Song library has no Song list")
    matching = [
        value for value in songs if isinstance(value, dict)
        and value.get("job_id") == job_id
        and (source is None or value.get("source_kind") == source)
    ]
    if len(matching) != 1:
        raise accepted.PackagedFeatureAcceptanceError(
            "Completed score Job did not reconcile to exactly one canonical Song"
        )
    song_id = matching[0].get("song_id")
    if not isinstance(song_id, str) or accepted._JOB_ID.fullmatch(song_id) is None:
        raise accepted.PackagedFeatureAcceptanceError("Canonical Song has an invalid identifier")
    return song_id


def _export_song(
    base: str, token: str, song_id: str, *, root: Path, formats: list[str],
) -> Path:
    """Ask the packaged renderer to export; keep all files under temporary QA."""
    if accepted._JOB_ID.fullmatch(song_id) is None:
        raise accepted.PackagedFeatureAcceptanceError("Invalid canonical Song for export")
    root.mkdir(parents=True, exist_ok=False)
    code, raw = accepted._http(
        base, token, "POST", f"/api/songs/{song_id}/export-to",
        data=json.dumps({
            "formats": formats, "destination_dir": str(root.resolve()),
        }).encode(),
        content_type="application/json",
        timeout=180,
    )
    data = accepted._json_ok(code, raw, name="packaged Song export")
    destination = data.get("destination")
    if not isinstance(destination, str):
        raise accepted.PackagedFeatureAcceptanceError("Packaged Song export returned no directory")
    output = Path(destination)
    if output.is_symlink() or not output.is_dir():
        raise accepted.PackagedFeatureAcceptanceError("Packaged Song export target is not a real directory")
    try:
        output.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise accepted.PackagedFeatureAcceptanceError(
            "Packaged Song export escaped the isolated acceptance workspace"
        ) from exc
    return output


def _read_generated_file(root: Path, name: str, magic: bytes) -> bytes:
    file = root / name
    minimum = 22 if name.endswith(".mid") else 100
    if (
        file.is_symlink() or not file.is_file()
        or not minimum <= file.stat().st_size <= _PDF_LIMIT
    ):
        raise accepted.PackagedFeatureAcceptanceError(f"Packaged export lacks a valid {name}")
    with file.open("rb") as source:
        header = source.read(len(magic))
    if header != magic:
        raise accepted.PackagedFeatureAcceptanceError(f"Packaged {name} has invalid file signature")
    return file.read_bytes()


def verify_embedded_pdf(base: str, token: str, *, workspace: Path) -> None:
    """Exercise bundled fonts and PDF export without an AMT/OMR component."""
    from scripts.smoke_audiveris_omr_product_e2e import make_owned_musicxml

    workspace.mkdir(parents=True, exist_ok=False)
    score = workspace / "owned-original.musicxml"
    make_owned_musicxml(score)
    document = ET.parse(score)
    document.find("part-list/score-part/part-name").text = "보컬 – PDF 검증"
    first = document.find("part/measure")
    direction = ET.SubElement(first, "direction")
    metronome = ET.SubElement(ET.SubElement(direction, "direction-type"), "metronome")
    ET.SubElement(metronome, "beat-unit").text = "quarter"
    ET.SubElement(metronome, "per-minute").text = "90"
    ET.SubElement(direction, "sound", tempo="90")
    ET.SubElement(ET.SubElement(first.find("note"), "lyric"), "text").text = "한글"
    document.write(score, encoding="utf-8", xml_declaration=True)
    job = _post_owned_file(
        base, token, route="/api/import/notation", filename="owned-original.musicxml",
        payload=score.read_bytes(), media_type="application/vnd.recordare.musicxml+xml",
        kind="notation-import",
    )
    accepted._await_job(base, token, job, timeout_seconds=90)
    song = _song_for_job(base, token, job)
    output = _export_song(base, token, song, root=workspace / "export", formats=["pdf"])
    payload = _read_generated_file(output, "score.pdf", b"%PDF-")
    if b"NotoSansKR" not in payload or b"Leipzig" not in payload:
        raise accepted.PackagedFeatureAcceptanceError("Packaged PDF did not embed text/music fonts")


def verify_real_pdf_omr(
    base: str, token: str, *, workspace: Path,
    timeout_seconds: float = 420,
) -> dict[str, Any]:
    """Original MusicXML→product PDF→Audiveris OMR Job→Song→product export."""
    if not 1 <= timeout_seconds <= 480:
        raise accepted.PackagedFeatureAcceptanceError("OMR timeout must be bounded to eight minutes")
    from scripts.smoke_audiveris_omr_product_e2e import make_owned_musicxml

    original_score = workspace / "authored-original.musicxml"
    created = make_owned_musicxml(original_score)
    xml_bytes = original_score.read_bytes()
    if (
        created.get("synthetic_pitched_notes") != 48
        or accepted._musicxml_note_count(xml_bytes) != (48, 1)
    ):
        raise accepted.PackagedFeatureAcceptanceError("Authored PDF-OMR fixture drifted")
    notation_id = _post_owned_file(
        base, token, route="/api/import/notation",
        filename="owned-original.musicxml", payload=xml_bytes,
        media_type="application/vnd.recordare.musicxml+xml",
        kind="notation-import",
    )
    job = accepted._await_job(base, token, notation_id, timeout_seconds=90)
    if job.get("kind") != "notation-import":
        raise accepted.PackagedFeatureAcceptanceError("Authored notation import Job has wrong kind")
    source_song = _song_for_job(base, token, notation_id)
    original_export = _export_song(
        base, token, source_song, root=workspace / "original-engraving",
        formats=["pdf"],
    )
    rendered_pdf = _read_generated_file(original_export, "score.pdf", b"%PDF-")
    if len(rendered_pdf) < 1024:
        raise accepted.PackagedFeatureAcceptanceError("Packaged original PDF renderer returned empty pages")
    pdf_sha = hashlib.sha256(rendered_pdf).hexdigest()
    omr_id = _post_owned_file(
        base, token, route="/api/import/score",
        filename="owned-rendered-score.pdf", payload=rendered_pdf,
        media_type="application/pdf", kind="omr",
    )
    recognized = accepted._await_job(
        base, token, omr_id, timeout_seconds=timeout_seconds,
    )
    if (
        recognized.get("kind") != "omr"
        or recognized["result"].get("omr_provider") != "audiveris"
    ):
        raise accepted.PackagedFeatureAcceptanceError("Packaged OMR Job did not use Audiveris")

    code, raw = accepted._http(base, token, "GET", f"/api/jobs/{omr_id}/files/musicxml")
    if code != 200:
        raise accepted.PackagedFeatureAcceptanceError(
            f"Managed Audiveris did not provide MusicXML over the packaged API (HTTP {code})"
        )
    notes, parts = accepted._musicxml_note_count(raw)
    if notes < _MIN_RECOGNIZED_NOTES:
        raise accepted.PackagedFeatureAcceptanceError("Managed Audiveris recognized too few pitched notes")
    recognized_song = _song_for_job(base, token, omr_id, source="omr")
    score_status, canonical = accepted._http(
        base, token, "GET", f"/api/songs/{recognized_song}/score",
    )
    if score_status != 200:
        raise accepted.PackagedFeatureAcceptanceError("OMR Song was not persisted as canonical SQLite score")
    canonical_notes, canonical_parts = accepted._musicxml_note_count(canonical)
    if canonical_notes < _MIN_RECOGNIZED_NOTES or canonical_parts < 1:
        raise accepted.PackagedFeatureAcceptanceError("OMR canonical Song lost its recognized notes")

    published = _export_song(
        base, token, recognized_song, root=workspace / "recognized-final-export",
        formats=["musicxml", "midi", "pdf", "parts"],
    )
    exported_xml = _read_generated_file(published, "score.musicxml", b"<?xml")
    exported_midi = _read_generated_file(published, "score.mid", b"MThd")
    _read_generated_file(published, "score.pdf", b"%PDF-")
    final_notes, final_parts = accepted._musicxml_note_count(exported_xml)
    if (
        final_notes < _MIN_RECOGNIZED_NOTES or final_parts < 1
        or accepted._midi_note_count(exported_midi) < 1
    ):
        raise accepted.PackagedFeatureAcceptanceError("OMR published score lacks real notes/parts")
    part_root = published / "parts"
    part_scores = list(part_root.glob("*.musicxml")) if part_root.is_dir() else []
    if not part_scores or any(
        item.is_symlink() or not item.is_file()
        or item.with_suffix(".pdf").is_symlink()
        or not item.with_suffix(".pdf").is_file()
        for item in part_scores
    ):
        raise accepted.PackagedFeatureAcceptanceError("OMR part exports are incomplete")

    return {
        "actual_pdf_omr_job_completed": True,
        "real_pdf_omr_accepted": True,
        "authored_original_score_sha256": created["synthetic_score_sha256"],
        "packaged_rendered_pdf_sha256": pdf_sha,
        "recognized_omr_musicxml_sha256": hashlib.sha256(raw).hexdigest(),
        "recognized_omr_pitched_notes": notes,
        "recognized_omr_parts": parts,
        "canonical_song_reconciliation_verified": True,
        "omr_musicxml_pdf_midi_parts_export_verified": True,
        "omr_license_independently_approved": False,
        "clean_machine_desktop_gui_verified": False,
    }
