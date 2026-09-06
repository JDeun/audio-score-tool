from __future__ import annotations

import os
import platform
import shutil
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


def _require_output(root: Path, name: str) -> Path:
    result = _find_one(root, name)
    if result is None:  # pragma: no cover - _find_one raises for required outputs
        raise TranscriptionEngineError(f"Expected engine output not found: {name} under {root}")
    return result


def _resolve_musescore(settings: Settings) -> str | None:
    if settings.musescore_cmd:
        return settings.musescore_cmd
    env_path = os.getenv("MUSCRIPTOR_MUSESCORE")
    if env_path:
        return env_path
    for candidate in ("mscore", "musescore", "MuseScore4", "musescore4", "MuseScore"):
        if shutil.which(candidate):
            return candidate
    for candidate in (
        "/Applications/MuseScore 4.app/Contents/MacOS/mscore",
        str(Path("~/MuseScore.AppImage").expanduser()),
        str(Path("~/Applications/MuseScore.AppImage").expanduser()),
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def _musescore_env() -> dict[str, str] | None:
    if platform.system() != "Linux":
        return None
    return {
        "QT_QPA_PLATFORM": "offscreen",
        "MU_QT_QPA_PLATFORM": "offscreen",
    }


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

    def describe(self) -> dict[str, object]:
        return {
            "key": self.key,
            "name": self.display_name,
            "ready": self.ready(),
            "commercial_status": self.commercial_status,
        }


class MT3InferEngine(BaseTranscriptionEngine):
    """Multi-instrument transcription through the MIT-licensed mt3-infer toolkit.

    The default model is MR-MT3. Its upstream repository and published checkpoint are
    both marked MIT. YourMT3 can also be selected for quality experiments, but it is
    not the commercial default because license metadata differs between upstream
    distributions and should be reviewed before a commercial release.
    """

    key = "mt3_infer"
    display_name = "MT3-Infer"
    commercial_status = "permissive_default"
    supported_models = {"mr_mt3", "yourmt3"}

    def ready(self) -> bool:
        return command_exists(self.settings.mt3_infer_cmd) and _resolve_musescore(self.settings) is not None

    def describe(self) -> dict[str, object]:
        model = self.settings.mt3_model
        status = "mit" if model == "mr_mt3" else "license_review_recommended"
        return {
            **super().describe(),
            "model": model,
            "model_commercial_status": status,
        }

    def transcribe(
        self,
        audio_path: Path,
        output_dir: Path,
        *,
        device: str,
        cancel_event: Event | None = None,
    ) -> TranscriptionArtifacts:
        if not command_exists(self.settings.mt3_infer_cmd):
            raise TranscriptionEngineUnavailable(
                "MT3-Infer is unavailable. Install mt3-infer or make uvx available."
            )
        model = self.settings.mt3_model.strip().lower()
        if model not in self.supported_models:
            raise TranscriptionEngineUnavailable(
                f"Unsupported MT3-Infer model: {model}. Use mr_mt3 or yourmt3."
            )
        musescore = _resolve_musescore(self.settings)
        if not musescore:
            raise TranscriptionEngineUnavailable(
                "MuseScore 4 is required to convert MT3-Infer multi-track MIDI to MusicXML."
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        midi_path = output_dir / "score.mid"
        musicxml_path = output_dir / "score.musicxml"
        try:
            run_command(
                self.settings.mt3_infer_cmd,
                [
                    "transcribe",
                    audio_path,
                    "-o",
                    midi_path,
                    "-m",
                    model,
                    "--device",
                    device,
                ],
                cancel_event=cancel_event,
            )
            if not midi_path.is_file():
                raise TranscriptionEngineError(
                    f"MT3-Infer did not produce the expected MIDI: {midi_path}"
                )
            run_command(
                musescore,
                ["-o", musicxml_path, midi_path],
                env=_musescore_env(),
                cancel_event=cancel_event,
            )
        except CommandCancelled as exc:
            raise TranscriptionEngineCancelled("MT3-Infer transcription cancelled.") from exc
        except CommandError as exc:
            raise TranscriptionEngineError(f"MT3-Infer failed.\n{exc}") from exc

        if not musicxml_path.is_file():
            raise TranscriptionEngineError(
                f"MuseScore did not create the expected MusicXML: {musicxml_path}"
            )
        return TranscriptionArtifacts(midi_path=midi_path, musicxml_path=musicxml_path)


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
            midi_path=_require_output(output_dir, "score.mid"),
            musicxml_path=_require_output(output_dir, "score.musicxml"),
            initial_pdf_path=_find_one(output_dir, "full_score.pdf", required=False),
        )


class NativeCommandEngine(BaseTranscriptionEngine):
    """Project-owned AudioScore Native command contract.

    Native remains an R&D/future ownership path. It is not the default because producing
    a high-quality checkpoint requires licensed data and substantial GPU training.
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
                "AudioScore Native checkpoint is not configured. "
                "Train or provide a project-owned checkpoint first."
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
            midi_path=_require_output(output_dir, "score.mid"),
            musicxml_path=_require_output(output_dir, "score.musicxml"),
            initial_pdf_path=_find_one(output_dir, "full_score.pdf", required=False),
        )


def available_engines(settings: Settings) -> list[dict[str, object]]:
    engines: list[BaseTranscriptionEngine] = [
        MT3InferEngine(settings),
        NativeCommandEngine(settings),
        MuScriptorEngine(settings),
    ]
    return [engine.describe() for engine in engines]


def resolve_transcription_engine(settings: Settings) -> BaseTranscriptionEngine:
    key = settings.transcription_engine.strip().lower()
    if key in {"mt3_infer", "yourmt3"}:  # `yourmt3` is a v0.7 prerelease migration alias.
        return MT3InferEngine(settings)
    if key == "muscriptor":
        return MuScriptorEngine(settings)
    if key == "native":
        return NativeCommandEngine(settings)
    raise TranscriptionEngineUnavailable(
        f"Unknown transcription engine: {settings.transcription_engine}"
    )
