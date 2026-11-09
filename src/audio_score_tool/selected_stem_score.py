"""Stem-targeted research-grade score drafts for selected musical roles.

Unlike the ordinary full-mix AMT path, these modes *actually transcribe* only
the requested separated audio stems. Each stem is checked before processing.
Demucs 6s guitar separation and MT3 vocal/guitar transcription are experimental:
no automatic TAB, verified melody accuracy or publishing-quality claims.
"""
from __future__ import annotations

import bisect
import copy
import math
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from threading import Event

import mido

from .auto_chords import infer_chords
from .config import Settings, packaged_runtime
from .demucs_runtime import demucs_repo_args, managed_demucs_repository
from .musicxml_metadata_projection import _score, project_musicxml_annotations
from .musicxml_parts import extract_part_musicxml
from .notation_backend import musicxml_to_midi
from .runner import CommandCancelled, CommandError, command_exists, run_command
from .score_requests import validate_score_mode
from .selected_stem_timeline import align_selected_role_scores
from .transcription_engine import (
    BaseTranscriptionEngine,
    TranscriptionArtifacts,
    TranscriptionEngineCancelled,
    TranscriptionEngineError,
)


class SelectedScoreError(RuntimeError):
    pass


def _stem(root: Path, name: str) -> Path:
    # Outputs are always created in a fresh app-owned workspace, never from
    # an arbitrary filename supplied by a request or another user's folder.
    paths = [p for p in root.rglob(f"{name}.wav") if p.is_file() and not p.is_symlink()]
    if len(paths) != 1 or paths[0].stat().st_size <= 44:
        raise SelectedScoreError(
            f"Demucs did not produce one nonempty {name} stem. "
            "The selected score was not created from the original mix."
        )
    return paths[0]


def _main_part(score_path: Path, destination: Path, *, part_name: str):
    """Extract the largest performed part without reserializing its note values.

    MT3 is a multi-instrument model, so even one isolated stem may yield several
    overlapping MIDI tracks. Keep one explicit, editable draft and warn that
    multi-source/program attribution is not established by the separator.
    """
    root = _score(score_path)
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    parts = root.findall(f"{ns}part")
    eligible = [(
        sum(n.find(f"{ns}pitch") is not None or n.find(f"{ns}unpitched") is not None
            for n in part.findall(f"{ns}measure/{ns}note")), index, part,
    ) for index, part in enumerate(parts)]
    if not eligible or max(eligible, key=lambda item: item[0])[0] == 0:
        raise SelectedScoreError(f"{part_name} stem produced no playable score notes")
    _count, _index, source = max(eligible, key=lambda item: (item[0], -item[1]))
    extract_part_musicxml(score_path, source.get("id"), destination)
    selected = _score(destination)
    part = selected.find(f"{ns}part")
    definition = selected.find(f"{ns}part-list/{ns}score-part")
    if part is None or definition is None:
        raise SelectedScoreError("Selected score part has no instrument definition")
    part_id = f"AST_{part_name.replace(' ', '_')}"
    part.set("id", part_id)
    definition.set("id", part_id)
    name = definition.find(f"{ns}part-name")
    if name is None:
        name = ET.SubElement(definition, f"{ns}part-name")
    name.text = part_name
    # Two independently transcribed stems can reuse P1/I1 identifiers. Keep
    # every source instrument binding distinct when the documents are joined.
    identifiers = {
        node.get("id"): f"{part_id}-{node.get('id')}"
        for node in definition if node.get("id")
    }
    for node in definition.iter():
        if node.get("id") in identifiers:
            node.set("id", identifiers[node.get("id")])
    for node in part.iter(f"{ns}instrument"):
        if node.get("id") in identifiers:
            node.set("id", identifiers[node.get("id")])
    return selected


def _score_clock(score):
    """Map score quarters to/from elapsed seconds, including every tempo change."""
    quarters, seconds, rates = [], [], []
    elapsed = 0.0
    for start, end, mark in score.metronomeMarkBoundaries():
        bpm = mark.getQuarterBPM()
        if bpm is None or not math.isfinite(bpm) or bpm <= 0:
            raise SelectedScoreError("Selected score contains an invalid tempo")
        quarters.append(float(start))
        seconds.append(elapsed)
        rates.append(60.0 / bpm)
        elapsed += float(end - start) * rates[-1]
    if not quarters:
        raise SelectedScoreError("Selected score has no usable time axis")

    def to_seconds(position):
        index = max(0, bisect.bisect_right(quarters, position) - 1)
        return seconds[index] + (position - quarters[index]) * rates[index]

    def to_quarters(position):
        index = max(0, bisect.bisect_right(seconds, position) - 1)
        return quarters[index] + (position - seconds[index]) / rates[index]

    return to_seconds, to_quarters


def _annotate_chords(source: Path, backing: Path, destination: Path, stage: Path) -> None:
    """Project backing harmony by elapsed audio time onto unchanged vocal notes."""
    from music21 import converter, harmony, note, stream

    parsed = converter.parse(str(source))
    accompaniment = converter.parse(str(backing))
    backing_measures = list(accompaniment.parts[0].getElementsByClass(stream.Measure))
    backing_seconds, _ = _score_clock(accompaniment)
    _, vocal_quarters = _score_clock(parsed)
    measures = list(parsed.parts[0].getElementsByClass(stream.Measure))
    starts = [float(m.getOffsetBySite(parsed.parts[0])) for m in measures]
    overlay = stream.Score()
    part = stream.Part()
    overlay.insert(0, part)
    for original in measures:
        measure = stream.Measure(number=original.number)
        if original.timeSignature is not None:
            measure.insert(0, copy.deepcopy(original.timeSignature))
        measure.insert(0, note.Rest(quarterLength=1))
        part.insert(original.getOffsetInHierarchy(parsed.parts[0]), measure)
    targets = list(part.getElementsByClass(stream.Measure))
    inserted = 0
    for candidate in infer_chords(backing):
        if not 0 <= candidate.measure_index < len(backing_measures):
            raise SelectedScoreError("Inferred chord has no corresponding backing measure")
        backing_offset = float(
            backing_measures[candidate.measure_index].getOffsetBySite(accompaniment.parts[0])
        ) + candidate.offset_quarters
        position = vocal_quarters(backing_seconds(backing_offset))
        if position < 0 or position >= float(parsed.parts[0].highestTime):
            continue  # Accompaniment can continue past the last vocal measure.
        target_index = max(0, bisect.bisect_right(starts, position) - 1)
        try:
            symbol = harmony.ChordSymbol(candidate.symbol)
            targets[target_index].insert(position - starts[target_index], symbol)
            inserted += 1
        except (ValueError, TypeError):
            continue
    if inserted == 0:
        raise SelectedScoreError(
            "No reliable accompaniment chords could be placed on the vocal "
            "melody. A chordless result will not be called a Lead Sheet."
        )
    overlay_path = stage / "harmony.musicxml"
    overlay.write("musicxml", fp=str(overlay_path), makeNotation=False)
    project_musicxml_annotations(
        source, overlay_path, destination, include_key=False, include_meter=False,
    )


def transcribe_selected_stems(
    audio_path: Path,
    output_dir: Path,
    stems_root: Path,
    *,
    score_mode: str,
    settings: Settings,
    engine: BaseTranscriptionEngine,
    device: str,
    demucs_device: str,
    cancel_event: Event | None = None,
) -> tuple[TranscriptionArtifacts, Path, list[str]]:
    """Split, transcribe and assemble requested stems as a real MusicXML draft.

    lead_sheet: Demucs 2-stem vocals/no_vocals -> vocal melody and chords
    estimated from AMT on the backing. guitar_vocal: experimental 6-stem
    vocals+guitar -> two role-labelled music21 parts.
    """
    mode = validate_score_mode(score_mode)
    if mode == "full":
        raise ValueError("Full score must use the existing whole-mix AMT pipeline")
    if not command_exists(settings.demucs_cmd) or (
        packaged_runtime() and managed_demucs_repository(settings) is None
    ):
        raise SelectedScoreError(
            "Selected-part scoring requires Demucs. Install an approved managed "
            "separator in Setup Center or choose the Full Score mode."
        )
    if stems_root.exists():
        raise SelectedScoreError("Selected-stem output already exists; refusing stale media")
    stems_root.mkdir(parents=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    model = "htdemucs" if mode == "lead_sheet" else "htdemucs_6s"
    # In a packaged app, only verified app-owned model weights are eligible;
    # --repo disables Demucs' automatic pretrained weight retrieval.
    args: list[str | Path] = ["-n", model, *demucs_repo_args(settings)]
    if mode == "lead_sheet":
        args += ["--two-stems", "vocals"]
    args += ["-d", demucs_device, "-o", stems_root, audio_path]
    try:
        run_command(settings.demucs_cmd, args, cancel_event=cancel_event)
    except CommandCancelled as exc:
        raise TranscriptionEngineCancelled("Requested stem separation cancelled") from exc
    except CommandError as exc:
        raise SelectedScoreError(f"Requested stem separation failed: {exc}") from exc

    vocals = _stem(stems_root, "vocals")
    guitar = _stem(stems_root, "guitar") if mode == "guitar_vocal" else None
    harmonic_audio = guitar if guitar is not None else _stem(stems_root, "no_vocals")

    try:
        vocal_artifacts = engine.transcribe(
            vocals, output_dir / "vocal", device=device, cancel_event=cancel_event,
        )
        harmonic_artifacts = engine.transcribe(
            harmonic_audio,
            output_dir / ("guitar" if guitar is not None else "accompaniment"),
            device=device, cancel_event=cancel_event,
        )
    except TranscriptionEngineCancelled:
        raise
    except TranscriptionEngineError as exc:
        raise SelectedScoreError(f"Selected-stem transcription failed: {exc}") from exc

    warnings = [
        "Stem-targeted score is an experimental, editable draft; "
        "source separation and instrument identities have not been independently verified."
    ]

    if guitar is not None:
        warnings.append(
            "Guitar stem uses experimental Demucs htdemucs_6s; "
            "this score contains standard notation, not verified guitar tablature."
        )
    midi_target = output_dir / "score.mid"
    musicxml_target = output_dir / "score.musicxml"
    try:
        with tempfile.TemporaryDirectory(prefix=".selected-score-", dir=output_dir) as folder:
            stage = Path(folder)
            vocal_xml = stage / "vocal.musicxml"
            root = _main_part(vocal_artifacts.musicxml_path, vocal_xml, part_name="Voice")
            assembled = stage / "assembled.musicxml"
            if guitar is not None:
                guitar_xml = stage / "guitar.musicxml"
                _main_part(harmonic_artifacts.musicxml_path, guitar_xml, part_name="Guitar")
                # XML parts can carry different tempo/meter maps. Reconstruct a
                # shared clock from their real elapsed seconds before joining.
                align_selected_role_scores(vocal_xml, guitar_xml, assembled, stage)
            else:
                ET.ElementTree(root).write(assembled, encoding="utf-8", xml_declaration=True)
            if guitar is None:
                annotated = stage / "annotated.musicxml"
                _annotate_chords(assembled, harmonic_artifacts.musicxml_path, annotated, stage)
                assembled = annotated
            midi = stage / "score.mid"
            musicxml_to_midi(assembled, midi)
            raw = mido.MidiFile(str(midi))
            performed = sum(
                message.type == "note_on" and message.velocity > 0
                for track in raw.tracks for message in track
            )
            if performed == 0:
                raise SelectedScoreError("Selected-part score contains no playable notes")
            midi.replace(midi_target)
            assembled.replace(musicxml_target)
    except Exception as exc:
        raise SelectedScoreError(f"Could not assemble playable selected-part score: {exc}") from exc
    if performed == 0 or not musicxml_target.is_file() or not musicxml_target.stat().st_size:
        raise SelectedScoreError("Selected-part score contains no playable notes")

    return TranscriptionArtifacts(midi_target, musicxml_target), vocals, warnings
