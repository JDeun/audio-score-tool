from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class WordTiming:
    text: str
    start: float
    end: float
    score: float | None = None


@dataclass(slots=True)
class DevicePlan:
    torch_device: str
    muscriptor_device: str
    demucs_device: str
    whisperx_device: str
    whisperx_compute_type: str

    def as_dict(self) -> dict[str, str]:
        return {
            "torch_device": self.torch_device,
            "muscriptor_device": self.muscriptor_device,
            "demucs_device": self.demucs_device,
            "whisperx_device": self.whisperx_device,
            "whisperx_compute_type": self.whisperx_compute_type,
        }


@dataclass(slots=True)
class PipelineResult:
    work_dir: Path
    score_dir: Path
    midi_path: Path
    musicxml_path: Path
    lyric_musicxml_path: Path | None
    pdf_path: Path | None
    transcript_json_path: Path | None
    vocals_path: Path | None
    chord_report_path: Path | None = None
    part_pdfs: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        def p(value: Path | None) -> str | None:
            return str(value) if value else None

        return {
            "work_dir": p(self.work_dir),
            "score_dir": p(self.score_dir),
            "midi": p(self.midi_path),
            "musicxml": p(self.musicxml_path),
            "lyric_musicxml": p(self.lyric_musicxml_path),
            "pdf": p(self.pdf_path),
            "transcript_json": p(self.transcript_json_path),
            "vocals": p(self.vocals_path),
            "chord_report": p(self.chord_report_path),
            "part_pdfs": [str(path) for path in self.part_pdfs],
            "warnings": self.warnings,
        }
