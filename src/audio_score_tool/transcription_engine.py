from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event

from .config import Settings
from .runner import CommandCancelled, CommandError, command_exists, run_command


class TranscriptionEngineError(RuntimeError):
    pass


class TranscriptionEngineUnavailable(TranscriptionEngineError):
    pass


class TranscriptionEngineCancelled(TranscriptionEngineError):
    pass


@dataclass(slots=True)
class TranscriptionArtifacts:
    midi_path: Path
    musicxml_path: Path
    initial_pdf_path: Path | None = None


def _find_one(root: Path, name: str, *, required: bool = True) -> Path | None:
    matches = list(root.rglob(name))
    if matches:
        return matches[0]
    if required:
        raise TranscriptionEngineError(f"Expected engine output not found: {name} under {root}")
    return None


class BaseTranscriptionEngine:
    key = "base"
    display_name = "Base"
    commercial_status = "unknown"

    def __init__(self, settings: Settings):
        self.settings = settings

    def ready(self) -> bool:
        raise NotImplementedError

    def transcribe(
        self,
        audio_path: Path,
        output_dir: Path,
        *,
        device: str,
        cancel_event: Event | None = None,
    ) -> TranscriptionArtifacts:
        raise NotImplementedError


class MuScriptorEngine(BaseTranscriptionEngine):
    key = "muscriptor"
    display_name = "MuScriptor"
    commercial_status = "noncommercial_weights"

    def ready(self) -> bool:
        return command_exists(self.settings.muscriptor_cmd)

    def transcribe(
        self,
        audio_path: Path,
        output_dir: Path,
        *,
        device: str,
        cancel_event: Event | None = None,
    ) -> TranscriptionArtifacts:
        if not self.ready():
            raise TranscriptionEngineUnavailable("MuScriptor command is unavailable.")
        args = [
            "transcribe",
            audio_path,
            "--format",
            "sheets",
            "--output",
            output_dir,
            "--device",
            device,
            "--model",
            self.settings.muscriptor_model,
            "--detect-tempo",
            "best-effort",
        ]
        try:
            run_command(self.settings.muscriptor_cmd, args, cancel_event=cancel_event)
        except CommandCancelled as exc:
            raise TranscriptionEngineCancelled("MuScriptor transcription cancelled.") from exc
        except CommandError as exc:
            raise TranscriptionEngineError(f"MuScriptor failed.\n{exc}") from exc
        return TranscriptionArtifacts(
            midi_path=_find_one(output_dir, "score.mid"),
            musicxml_path=_find_one(output_dir, "score.musicxml"),
            initial_pdf_path=_find_one(output_dir, "full_score.pdf", required=False),
        )


class NativeCommandEngine(BaseTranscriptionEngine):
    """AudioScore Native command contract.

    The native runtime is intentionally a separate executable so trained weights and
    accelerator-specific dependencies can be packaged independently from the desktop
    orchestration sidecar. The command must emit score.mid and score.musicxml.
    """

    key = "native"
    display_name = "AudioScore Native"
    commercial_status = "project_owned"

    def ready(self) -> bool:
        if not command_exists(self.settings.native_engine_cmd):
            return False
        checkpoint = self.settings.native_checkpoint
        return checkpoint is not None and checkpoint.expanduser().is_file()

    def transcribe(
        self,
        audio_path: Path,
        output_dir: Path,
        *,
        device: str,
        cancel_event: Event | None = None,
    ) -> TranscriptionArtifacts:
        checkpoint = self.settings.native_checkpoint
        if checkpoint is None or not checkpoint.expanduser().is_file():
            raise TranscriptionEngineUnavailable(
                "AudioScore Native checkpoint is not configured. Train or provide a project-owned checkpoint first."
            )
        if not command_exists(self.settings.native_engine_cmd):
            raise TranscriptionEngineUnavailable("AudioScore Native command is unavailable.")
        args = [
            "transcribe",
            audio_path,
            "--output",
            output_dir,
            "--checkpoint",
            checkpoint.expanduser(),
            "--device",
            device,
        ]
        try:
            run_command(self.settings.native_engine_cmd, args, cancel_event=cancel_event)
        except CommandCancelled as exc:
            raise TranscriptionEngineCancelled("AudioScore Native transcription cancelled.") from exc
        except CommandError as exc:
            raise TranscriptionEngineError(f"AudioScore Native failed.\n{exc}") from exc
        return TranscriptionArtifacts(
            midi_path=_find_one(output_dir, "score.mid"),
            musicxml_path=_find_one(output_dir, "score.musicxml"),
            initial_pdf_path=_find_one(output_dir, "full_score.pdf", required=False),
        )


def available_engines(settings: Settings) -> list[dict[str, object]]:
    engines: list[BaseTranscriptionEngine] = [MuScriptorEngine(settings), NativeCommandEngine(settings)]
    return [
        {
            "key": engine.key,
            "name": engine.display_name,
            "ready": engine.ready(),
            "commercial_status": engine.commercial_status,
        }
        for engine in engines
    ]


def resolve_transcription_engine(settings: Settings) -> BaseTranscriptionEngine:
    key = settings.transcription_engine.strip().lower()
    if key == "muscriptor":
        return MuScriptorEngine(settings)
    if key == "native":
        return NativeCommandEngine(settings)
    raise TranscriptionEngineUnavailable(f"Unknown transcription engine: {settings.transcription_engine}")
