"""Stem-targeted research-grade score drafts for selected musical roles.

Unlike the ordinary full-mix AMT path, these modes *actually transcribe* only
the requested separated audio stems. Each stem is checked before processing.
Demucs 6s guitar separation and MT3 vocal/guitar transcription are experimental:
no automatic TAB, verified melody accuracy or publishing-quality claims.
"""
from __future__ import annotations

import copy
from pathlib import Path
from threading import Event
from typing import Any

import mido

from .auto_chords import infer_chords
from .config import Settings
from .runner import CommandCancelled, CommandError, command_exists, run_command
from .score_requests import validate_score_mode
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


def _main_part(score_path: Path, *, part_name: str):
    """Choose the largest note-bearing part without inventing extra instruments.

    MT3 is a multi-instrument model, so even one isolated stem may yield several
    overlapping MIDI tracks. Keep one explicit, editable draft and warn that
    multi-source/program attribution is not established by the separator.
    """
    from music21 import converter

    parsed = converter.parse(str(score_path))
    parts = list(parsed.parts)
    if not parts:
        parts = [parsed]
    eligible = [(sum(1 for _ in part.recurse().notes), index, part)
                for index, part in enumerate(parts)]
    if not eligible or max(eligible, key=lambda item: item[0])[0] == 0:
        raise SelectedScoreError(f"{part_name} stem produced no playable score notes")
    _count, _index, source = max(eligible, key=lambda item: (item[0], -item[1]))
    selected = copy.deepcopy(source)
    selected.partName = part_name
    selected.id = f"AST_{part_name.replace(' ', '_')}"
    return selected


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
    if not command_exists(settings.demucs_cmd):
        raise SelectedScoreError(
            "Selected-part scoring requires Demucs. Install an approved managed "
            "separator in Setup Center or choose the Full Score mode."
        )
    if stems_root.exists():
        raise SelectedScoreError("Selected-stem output already exists; refusing stale media")
    stems_root.mkdir(parents=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    model = "htdemucs" if mode == "lead_sheet" else "htdemucs_6s"
    args: list[str | Path] = ["-n", model]
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

    from music21 import harmony, instrument, stream

    score = stream.Score()
    vocal_part = _main_part(vocal_artifacts.musicxml_path, part_name="Voice")
    vocal_part.insert(0, instrument.Vocalist())
    score.insert(0, vocal_part)
    warnings = [
        "Stem-targeted score is an experimental, editable draft; "
        "source separation and instrument identities have not been independently verified."
    ]

    if guitar is not None:
        guitar_part = _main_part(harmonic_artifacts.musicxml_path, part_name="Guitar")
        guitar_part.insert(0, instrument.Guitar())
        score.insert(0, guitar_part)
        warnings.append(
            "Guitar stem uses experimental Demucs htdemucs_6s; "
            "this score contains standard notation, not verified guitar tablature."
        )
    else:
        # Do not infer chord symbols from the vocal melody alone. The backing
        # sound has been transcribed independently using the same score engine.
        candidates = infer_chords(harmonic_artifacts.musicxml_path)
        measures = list(vocal_part.getElementsByClass(stream.Measure))
        inserted = 0
        for chord in candidates:
            if not 0 <= chord.measure_index < len(measures):
                continue
            try:
                symbol = harmony.ChordSymbol(chord.symbol)
                measures[chord.measure_index].insert(chord.offset_quarters, symbol)
                inserted += 1
            except (ValueError, TypeError):
                continue
        if inserted == 0:
            raise SelectedScoreError(
                "No reliable accompaniment chords could be placed on the vocal "
                "melody. A chordless result will not be called a Lead Sheet."
            )

    midi_target = output_dir / "score.mid"
    musicxml_target = output_dir / "score.musicxml"
    try:
        score.write("musicxml", fp=str(musicxml_target))
        score.write("midi", fp=str(midi_target))
        raw = mido.MidiFile(str(midi_target))
        performed = sum(
            message.type == "note_on" and message.velocity > 0
            for track in raw.tracks for message in track
        )
    except Exception as exc:
        raise SelectedScoreError(f"Could not assemble playable selected-part score: {exc}") from exc
    if performed == 0 or not musicxml_target.is_file() or not musicxml_target.stat().st_size:
        raise SelectedScoreError("Selected-part score contains no playable notes")

    return TranscriptionArtifacts(midi_target, musicxml_target), vocals, warnings
