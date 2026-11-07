"""Review-only real Audiveris OMR through the AudioScoreTool packaged API.

A new original, intentionally simple MusicXML score is engraved into a PDF by
AudioScoreTool's bundled Verovio/fpdf2 backend. Actual SHA-verified Audiveris
5.11.0+JRE must recognize the printed PDF and produce MXL/MusicXML via
POST /api/import/score, with packaged PATH fallback disabled. The same
temporary FastAPI/SQLite app must ingest the Song, edit its notes and credits,
then explicitly export score.musicxml/.pdf/.mid and parts through the product.

No external sheet music, model checkpoint or PDF is downloaded; the upstream
MSI/DMG and portable ZIP remain ephemeral. Only a pending JSON is emitted.
This is not an OMR accuracy benchmark, AGPL approval or public distribution.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from audio_score_tool.managed_components import (
    ComponentArtifact,
    ComponentError,
    install_component_artifact,
)
from scripts.verify_audiveris_native_layout import _find_runtime, _platform_matches
from scripts.verify_audiveris_official_installer import AudiverisReviewError, _sha256

_MAX_EVIDENCE_SIZE = 1024 * 1024
_MAX_PDF_BYTES = 32 * 1024 * 1024
_MAX_JOB_WAIT_SECONDS = 480
_PINNED_VERSION = "5.11.0-review-1"
_SHA = re.compile(r"^[a-f0-9]{64}$")


def _pending_receipt(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_EVIDENCE_SIZE:
        raise AudiverisReviewError("Audiveris portable candidate receipt is missing or unsafe.")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise AudiverisReviewError("Audiveris portable candidate receipt is invalid.") from exc
    if not isinstance(receipt, dict):
        raise AudiverisReviewError("Audiveris portable candidate receipt must be an object.")
    return receipt


def _archive_contract(
    *, archive: Path, pending: Path, target: str
) -> dict[str, Any]:
    if not _platform_matches(target):
        raise AudiverisReviewError("OMR product acceptance must run on the exact native OS/CPU.")
    if archive.is_symlink() or not archive.is_file() or archive.suffix.lower() != ".zip":
        raise AudiverisReviewError("OMR source must be a verified, regular local ZIP.")
    receipt = _pending_receipt(pending)
    expected_boolean = {
        "local_managed_zip_install_verified": True,
        "relocated_audiveris_version_verified": True,
        "relocated_embedded_jre_version_verified": True,
        "full_omr_to_musicxml_verified": False,
        "verified_launcher_uses_embedded_java": False,
        "remote_artifact_published": False,
        "clean_machine_verified": False,
        "approval_required": True,
    }
    if (
        receipt.get("schema") != 1
        or receipt.get("component") != "audiveris"
        or receipt.get("target") != target
        or receipt.get("version") != _PINNED_VERSION
        or receipt.get("redistribution_status") != "pending"
        or receipt.get("legal_review_status") != "pending"
        or receipt.get("source_commit") != "9e1e55cd2746037d059345881c53e6a6754bffbd"
        or any(receipt.get(name) is not expected for name, expected in expected_boolean.items())
    ):
        raise AudiverisReviewError("Unapproved Audiveris candidate contract is incomplete.")
    for field in (
        "archive_sha256", "source_asset_sha256", "source_receipt_sha256",
        "native_receipt_sha256", "review_pin_sha256", "launcher_sha256",
        "java_sha256", "archive_members_sha256",
    ):
        value = receipt.get(field)
        if not isinstance(value, str) or _SHA.fullmatch(value) is None:
            raise AudiverisReviewError(f"Candidate evidence lacks a valid {field}.")
    if _sha256(archive) != receipt["archive_sha256"]:
        raise AudiverisReviewError("Portable candidate ZIP differs from SHA-pinned pending receipt.")
    names = (receipt.get("tool_path"), receipt.get("embedded_jre_path"))
    for name in names:
        if (
            not isinstance(name, str) or not name.strip()
            or "\\" in name or name.startswith("/")
            or any(part in {"", ".", ".."} for part in name.split("/"))
        ):
            raise AudiverisReviewError("Audiveris portable executable mapping is unsafe.")
    return receipt


def make_owned_musicxml(destination: Path) -> dict[str, Any]:
    """Generate an original 12-bar quarter-note scale: no copyrighted repertoire."""
    if destination.exists():
        raise FileExistsError("The original synthetic MusicXML must not overwrite existing work.")
    root = ET.Element("score-partwise", {"version": "4.0"})
    listing = ET.SubElement(root, "part-list")
    score_part = ET.SubElement(listing, "score-part", {"id": "P1"})
    ET.SubElement(score_part, "part-name").text = "Flute"
    ET.SubElement(score_part, "part-abbreviation").text = "Fl."
    part = ET.SubElement(root, "part", {"id": "P1"})
    melody = [
        ("C", 5), ("D", 5), ("E", 5), ("F", 5),
        ("G", 5), ("F", 5), ("E", 5), ("D", 5),
        ("C", 5), ("E", 5), ("G", 5), ("E", 5),
        ("F", 5), ("E", 5), ("D", 5), ("C", 5),
    ]
    for measure_number in range(1, 13):
        measure = ET.SubElement(part, "measure", {"number": str(measure_number)})
        if measure_number in {5, 9}:
            ET.SubElement(measure, "print", {"new-system": "yes"})
        if measure_number == 1:
            attributes = ET.SubElement(measure, "attributes")
            ET.SubElement(attributes, "divisions").text = "10080"
            key = ET.SubElement(attributes, "key")
            ET.SubElement(key, "fifths").text = "0"
            meter = ET.SubElement(attributes, "time")
            ET.SubElement(meter, "beats").text = "4"
            ET.SubElement(meter, "beat-type").text = "4"
            clef = ET.SubElement(attributes, "clef")
            ET.SubElement(clef, "sign").text = "G"
            ET.SubElement(clef, "line").text = "2"
        start = ((measure_number - 1) * 4) % len(melody)
        for step, octave in melody[start : start + 4]:
            note = ET.SubElement(measure, "note")
            pitch = ET.SubElement(note, "pitch")
            ET.SubElement(pitch, "step").text = step
            ET.SubElement(pitch, "octave").text = str(octave)
            ET.SubElement(note, "duration").text = "10080"
            ET.SubElement(note, "type").text = "quarter"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
    return {
        "schema": 1, "synthetic_measures": 12,
        "synthetic_pitched_notes": 48,
        "synthetic_score_sha256": _sha256(destination),
    }


def _response_ok(response, label: str, *, status: int = 200) -> Any:
    if response.status_code != status:
        detail = response.text[:1400]
        raise AudiverisReviewError(
            f"{label}: AudioScoreTool API returned {response.status_code} "
            f"(expected {status}): {detail}"
        )
    return response.json()


def _bounded_job(client, job_id: str, *, timeout_seconds: int) -> dict:
    if timeout_seconds < 1 or timeout_seconds > _MAX_JOB_WAIT_SECONDS:
        raise AudiverisReviewError("OMR Job timeout must be bounded to at most eight minutes.")
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        job = _response_ok(client.get(f"/api/jobs/{job_id}"), "OMR Job status")
        status = job.get("status")
        if status in {"done", "failed", "cancelled", "interrupted"}:
            if status != "done":
                error = str(job.get("error") or "OMR job did not finish successfully")
                # run_command() preserves a bounded tail of the real Java log.
                # Prioritizing only its prefix hides the useful Java exception
                # and makes headless native CI failures impossible to diagnose.
                diagnostic = error if len(error) <= 7500 else (
                    error[:650] + "\n[... bounded native log tail ...]\n" + error[-6000:]
                )
                raise AudiverisReviewError(f"Actual Audiveris OMR job {status}: {diagnostic}")
            return job
        time.sleep(1)
    client.post(f"/api/jobs/{job_id}/cancel")
    raise AudiverisReviewError("Actual Audiveris OMR job exceeded the bounded native timeout.")


def _assert_score_with_notes(xml_text: str) -> tuple[int, int]:
    upper = xml_text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise AudiverisReviewError("Audiveris output may not contain DOCTYPE/ENTITY.")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise AudiverisReviewError("Audiveris output is not valid MusicXML.") from exc
    if root.tag.rsplit("}", 1)[-1] not in {"score-partwise", "score-timewise"}:
        raise AudiverisReviewError("Audiveris output lacks a MusicXML score root.")
    parts = [child for child in root if child.tag.rsplit("}", 1)[-1] == "part"]
    notes = [
        element for part in parts
        for element in part.iter()
        if element.tag.rsplit("}", 1)[-1] == "note"
        and any(node.tag.rsplit("}", 1)[-1] == "pitch" for node in element)
    ]
    if not parts or len(notes) < 4:
        raise AudiverisReviewError(
            "Audiveris produced a score without at least one part and four pitched notes."
        )
    return len(parts), len(notes)


def run_real_omr_product_flow(
    *,
    archive: Path,
    candidate_receipt: Path,
    target: str,
    destination: Path,
    job_timeout: int = 360,
) -> dict[str, Any]:
    receipt = _archive_contract(archive=archive, pending=candidate_receipt, target=target)
    if not destination.parent.is_dir() or destination.exists() or destination.is_symlink():
        raise AudiverisReviewError("OMR native E2E evidence must be a new file under an existing directory.")

    # Windows may keep SQLite file handles open for the lifetime of the
    # FastAPI singleton module. The OS runner owns and deletes this entire
    # ephemeral workspace; a locked DB during teardown must not replace the
    # actual product-E2E verdict or create a false regression.
    with tempfile.TemporaryDirectory(
        prefix="ast-real-omr-product-", ignore_cleanup_errors=True
    ) as scratch:
        root = Path(scratch).resolve()
        managed = root / "components"
        app_data = root / "app-data"
        app_data.mkdir()
        artifact = ComponentArtifact(
            component="audiveris",
            version=_PINNED_VERSION,
            url="https://example.invalid/never-publish-local-omr-review",
            sha256=receipt["archive_sha256"],
            archive="zip",
            tools={"audiveris": receipt["tool_path"]},
            license="AGPL-3.0",
            provenance="Exact Audiveris 5.11.0 official MSI/DMG + pinned native receipt; pending only",
        )
        installed = install_component_artifact(
            artifact, root=managed, local_archive=archive,
        )
        if installed.get("ready") is not True or installed.get("integrity") != "verified":
            raise AudiverisReviewError("Installed Audiveris ZIP failed managed integrity validation.")
        installed_dir = (managed / "installed" / "audiveris" / _PINNED_VERSION).resolve()
        audiveris, java, _java_release = _find_runtime(installed_dir, target)
        if (
            _sha256(audiveris) != receipt["launcher_sha256"]
            or _sha256(java) != receipt["java_sha256"]
            or audiveris.relative_to(installed_dir).as_posix() != receipt["tool_path"]
            or java.relative_to(installed_dir).as_posix() != receipt["embedded_jre_path"]
        ):
            raise AudiverisReviewError("Relocated Audiveris/JRE bytes or paths differ from pinned review.")

        # These settings are established BEFORE importing FastAPI singleton
        # routes and their SQLite stores: the actual packaged app code creates
        # the Job/Song/Revision/Publication DB under this temporary APP_DATA.
        os.environ["AST_DATA_DIR"] = str(app_data)
        os.environ["AST_COMPONENT_DIR"] = str(managed)
        os.environ["AST_PACKAGED"] = "1"
        os.environ["AST_API_TOKEN"] = "native-review-local-only-token"
        os.environ["PATH"] = ""
        os.environ["PYTHONNOUSERSITE"] = "1"

        from fastapi.testclient import TestClient

        from audio_score_tool.api import app
        from audio_score_tool.managed_tool_resolver import registered_managed_tool
        from audio_score_tool.notation_backend import render_pdf
        from audio_score_tool.paths import database_path, song_assets_dir

        registered = registered_managed_tool("audiveris")
        if registered is None or registered.resolve() != audiveris:
            raise AudiverisReviewError(
                "Packaged application did not resolve the SHA-registered Audiveris tool."
            )
        source_xml = root / "generated-original.musicxml"
        generated = make_owned_musicxml(source_xml)
        input_pdf = root / "owned-original-score.pdf"
        result_pdf, renderer = render_pdf(source_xml, input_pdf)
        if (
            renderer != "verovio-fpdf2" or result_pdf != input_pdf
            or not input_pdf.is_file() or not input_pdf.read_bytes().startswith(b"%PDF-")
            or input_pdf.stat().st_size > _MAX_PDF_BYTES
        ):
            raise AudiverisReviewError("Product's embedded notation renderer did not create a bounded PDF.")
        pdf_sha = _sha256(input_pdf)

        # Actual REST ingress/worker/reconciliation/edits/export, NOT private
        # calls that bypass app validation, JobStore or SongStore.
        with TestClient(app, headers={"X-AudioScore-Token": os.environ["AST_API_TOKEN"]}) as client:
            unauthorized = client.get("/api/omr/status", headers={"X-AudioScore-Token": ""})
            if unauthorized.status_code != 401:
                raise AudiverisReviewError("Packaged API failed to enforce local token authentication.")
            status = _response_ok(client.get("/api/omr/status"), "OMR readiness")
            if status.get("ready") is not True or Path(str(status.get("command"))).resolve() != audiveris:
                raise AudiverisReviewError("Packaged /api/omr/status did not bind to managed Audiveris.")
            payload = {"file": ("owned-original-score.pdf", input_pdf.read_bytes(), "application/pdf")}
            created = _response_ok(
                client.post("/api/import/score", files=payload),
                "real PDF OMR import", status=202,
            )
            if created.get("kind") != "omr" or not created.get("job_id"):
                raise AudiverisReviewError("OMR import did not register an actual Job.")
            job_id = str(created["job_id"])
            job = _bounded_job(client, job_id, timeout_seconds=job_timeout)
            if job.get("kind") != "omr":
                raise AudiverisReviewError("Completed OMR Job has the wrong kind.")
            result = job.get("result") or {}
            score_path = Path(str(result.get("musicxml") or ""))
            if (
                not score_path.is_file()
                or not score_path.resolve().is_relative_to(app_data)
                or score_path.stat().st_size > 64 * 1024 * 1024
            ):
                raise AudiverisReviewError("Audiveris did not produce a bounded owned MusicXML artifact.")
            recognized_xml = score_path.read_text(encoding="utf-8-sig")
            part_count, notes_count = _assert_score_with_notes(recognized_xml)
            omr_xml_sha = _sha256(score_path)

            library = _response_ok(client.get("/api/songs"), "Job to Song reconciliation")
            songs = [
                song for song in library.get("songs", [])
                if song.get("job_id") == job_id and song.get("source_kind") == "omr"
            ]
            if len(songs) != 1:
                raise AudiverisReviewError("Actual completed OMR Job did not yield one canonical SQLite Song.")
            song = songs[0]
            song_id = str(song["song_id"])
            asset_path = song_assets_dir() / song_id / "original-score.pdf"
            if not asset_path.is_file() or _sha256(asset_path) != pdf_sha:
                raise AudiverisReviewError("Original PDF was not preserved under Song managed assets.")
            # Ensure actual SQLite canonical state (not only cached XML) is present.
            from audio_score_tool.song_routes import _song_store
            canonical_before = _song_store.score_xml(song_id)
            _assert_score_with_notes(canonical_before)
            initial_revision = int(song["revision"])

            note_summary = _response_ok(client.get(f"/api/songs/{song_id}/notes"), "Inspector note listing")
            pitched = next(
                (n for n in note_summary.get("notes", [])
                 if not n.get("rest") and n.get("step") in {"A", "B", "C", "D", "E", "F", "G"}),
                None,
            )
            if pitched is None:
                raise AudiverisReviewError("The Inspector found no editable pitched OMR note.")
            expected_new_step = "G" if pitched["step"] != "G" else "E"
            note_edited = _response_ok(
                client.patch(
                    f"/api/songs/{song_id}/notes/{pitched['note_id']}",
                    json={"step": expected_new_step},
                ),
                "Inspector pitch edit",
            )
            revision_after_note = int(note_edited["song"]["revision"])
            if revision_after_note <= initial_revision:
                raise AudiverisReviewError("OMR note edit did not create a persisted Revision.")

            title = "Original Synthetic OMR Integration"
            credit_edited = _response_ok(
                client.patch(
                    f"/api/songs/{song_id}/credits",
                    json={
                        "title": title,
                        "artist": "AudioScoreTool CI-owned score",
                        "expected_revision": revision_after_note,
                    },
                ),
                "atomic title/credits edit",
            )
            final_revision = int(credit_edited["song"]["revision"])
            if final_revision != revision_after_note + 1:
                raise AudiverisReviewError("Atomic OMR credits save did not create exactly one Revision.")
            final_xml = _song_store.score_xml(song_id)
            _assert_score_with_notes(final_xml)
            if expected_new_step not in final_xml:
                raise AudiverisReviewError("Edited OMR pitch was not saved to SQLite MusicXML.")

            export_dir = root / "final-export-target"
            export_dir.mkdir()
            final = _response_ok(
                client.post(
                    f"/api/songs/{song_id}/export-to",
                    json={
                        "formats": ["musicxml", "pdf", "midi", "parts"],
                        "destination_dir": str(export_dir),
                    },
                ),
                "explicit multi-format publication",
            )
            published = Path(str(final.get("destination") or ""))
            expected = ("score.musicxml", "score.pdf", "score.mid")
            if not published.is_dir() or not published.is_relative_to(export_dir):
                raise AudiverisReviewError("Explicit OMR export escaped the owned destination.")
            for name in expected:
                file = published / name
                if not file.is_file() or file.stat().st_size < 8:
                    raise AudiverisReviewError(f"OMR export is missing a nonempty {name}.")
            if not (published / "score.pdf").read_bytes().startswith(b"%PDF-"):
                raise AudiverisReviewError("OMR final publication did not emit a PDF.")
            if not (published / "score.mid").read_bytes().startswith(b"MThd"):
                raise AudiverisReviewError("OMR final publication did not emit a valid MIDI file.")
            final_xml_export = (published / "score.musicxml").read_text(encoding="utf-8")
            _assert_score_with_notes(final_xml_export)
            parts = sorted((published / "parts").glob("*.musicxml"))
            if not parts or any(
                not part.with_suffix(".pdf").is_file() for part in parts
            ):
                raise AudiverisReviewError("OMR final publication lacks score part XML/PDF pairs.")
            after = _response_ok(client.get(f"/api/songs/{song_id}"), "Final Song status")
            if after.get("revision") != final_revision:
                raise AudiverisReviewError("OMR Song revision was not persisted after export.")

        if not database_path().is_file():
            raise AudiverisReviewError("Canonical SQLite database does not exist after OMR import.")
        report = {
            "schema": 1, "component": "audiveris", "target": target,
            "upstream_version": "5.11.0",
            "official_installer_sha256": receipt["source_asset_sha256"],
            "portable_candidate_archive_sha256": receipt["archive_sha256"],
            "portable_candidate_receipt_sha256": _sha256(candidate_receipt),
            "relocated_launcher_sha256": receipt["launcher_sha256"],
            "relocated_embedded_jre_sha256": receipt["java_sha256"],
            "exact_managed_tool_registered": True,
            "packaged_mode_without_system_path": True,
            "runtime_api_token_enforced": True,
            "synthetic_source_sha256": generated["synthetic_score_sha256"],
            "synthetic_source_measures": generated["synthetic_measures"],
            "synthetic_printed_pdf_sha256": pdf_sha,
            "actual_audiveris_omr_job_completed": True,
            "actual_omr_musicxml_sha256": omr_xml_sha,
            "recognized_parts": part_count, "recognized_pitched_notes": notes_count,
            "canonical_sqlite_song_ingested": True, "source_pdf_asset_preserved": True,
            "inspector_note_edit_verified": True, "atomic_credits_revision_verified": True,
            "final_revision": final_revision,
            "explicit_musicxml_pdf_midi_parts_export_verified": True,
            "exported_part_count": len(parts),
            "actual_score_content_quality_approved": False,
            "scanned_music_benchmark_executed": False,
            "ocr_language_assets_verified": False,
            "agpl_jre_redistribution_approved": False,
            "public_binary_or_score_artifact_published": False,
            "clean_machine_desktop_installer_verified": False,
            "redistribution_status": "pending", "approval_required": True,
        }
    if destination.exists() or destination.is_symlink():
        raise AudiverisReviewError("OMR review report must not overwrite existing evidence.")
    with destination.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, ensure_ascii=False, sort_keys=True)
        output.write("\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Real original PDF→managed Audiveris→MusicXML→SQLite Song→edit/export (review only)."
    )
    parser.add_argument("--target", required=True, choices=("windows-x86_64", "macos-aarch64"))
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--candidate-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--job-timeout", type=int, default=360)
    args = parser.parse_args()
    try:
        result = run_real_omr_product_flow(
            archive=args.archive, candidate_receipt=args.candidate_receipt,
            target=args.target, destination=args.output, job_timeout=args.job_timeout,
        )
    except (AudiverisReviewError, OSError, ComponentError, ValueError) as exc:
        parser.exit(2, f"Real Audiveris OMR product acceptance failed: {exc}\n")
    print(json.dumps({
        "target": result["target"], "actual_audiveris_omr_job_completed": True,
        "canonical_sqlite_song_ingested": True,
        "explicit_musicxml_pdf_midi_parts_export_verified": True,
        "redistribution_status": "pending",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
