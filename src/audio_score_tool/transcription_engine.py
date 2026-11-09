from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event

from .config import Settings, packaged_runtime
from .managed_tool_resolver import registered_managed_component_root
from .muscriptor_cache import cached_muscriptor_checkpoint, hf_home
from .notation_backend import NotationBackendError, backend_status, midi_to_musicxml
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
    if result is None:  # pragma: no cover
        raise TranscriptionEngineError(f"Expected engine output not found: {name} under {root}")
    return result


class BaseTranscriptionEngine:
    key = "base"
    display_name = "Base"
    commercial_status = "unknown"
    quality_rank = 99
    task_family = "automatic_music_transcription"
    input_mode = "mixed_audio"
    supports_polyphonic = True
    supports_multi_instrument = True
    supports_real_time = False

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
            "quality_rank": self.quality_rank,
            "task_family": self.task_family,
            "input_mode": self.input_mode,
            "supports_polyphonic": self.supports_polyphonic,
            "supports_multi_instrument": self.supports_multi_instrument,
            "supports_real_time": self.supports_real_time,
            "allowed_for_usage_mode": not (
                self.settings.usage_mode == "commercial"
                and self.commercial_status == "noncommercial_weights"
            ),
        }


class MT3InferEngine(BaseTranscriptionEngine):
    key = "mt3_infer"
    display_name = "MT3-Infer"
    commercial_status = "commercial_candidate"
    quality_rank = 2
    supported_models = {"mr_mt3", "yourmt3"}
    _checkpoint_extensions = frozenset({
        ".pt", ".pth", ".ckpt", ".bin", ".safetensors", ".h5", ".msgpack",
    })

    def _packaged_checkpoint_root(self) -> Path | None:
        """Require shipped, fully verified weights instead of upstream auto-download.

        MT3-Infer reads MT3_CHECKPOINT_DIR/<model> in both CLI and Python use.
        Only a pinned installed transcription_engine component can supply it.
        """
        if not packaged_runtime():
            return None
        model = self.settings.mt3_model.strip().lower()
        if model not in self.supported_models:
            return None
        installed = registered_managed_component_root(
            "transcription_engine", required_tool="mt3-infer",
        )
        if installed is None:
            return None
        checkpoint_root = installed / "checkpoints"
        selected = checkpoint_root / model
        if selected.is_symlink() or not selected.is_dir():
            return None
        try:
            has_weights = any(
                file.is_file()
                and not file.is_symlink()
                and file.suffix.lower() in self._checkpoint_extensions
                and file.stat().st_size > 0
                for file in selected.rglob("*")
            )
        except OSError:
            return None
        return checkpoint_root if has_weights else None

    def ready(self) -> bool:
        if not (
            command_exists(self.settings.mt3_infer_cmd)
            and backend_status(self.settings)["music21"]
        ):
            return False
        return not packaged_runtime() or self._packaged_checkpoint_root() is not None

    def describe(self) -> dict[str, object]:
        model = self.settings.mt3_model
        if model == "mr_mt3":
            status = "mit"
            rank = 3
            note = "빠르고 permissive한 fallback"
        else:
            status = "apache_checkpoint_review_distribution"
            rank = 2
            note = "MT3 계열 정확도 우선; 상용 배포 전 provenance 검토"
        return {
            **super().describe(),
            "model": model,
            "model_commercial_status": status,
            "quality_rank": rank,
            "quality_note": note,
            "midi_to_musicxml": backend_status(self.settings),
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
            if packaged_runtime():
                raise TranscriptionEngineUnavailable(
                    "The packaged MT3-Infer runtime or checkpoint is missing or unverified. "
                    "Reinstall the managed transcription runtime in Setup Center."
                )
            raise TranscriptionEngineUnavailable(
                "MT3-Infer is unavailable. Install mt3-infer or make uvx available."
            )
        model = self.settings.mt3_model.strip().lower()
        if model not in self.supported_models:
            raise TranscriptionEngineUnavailable(
                f"Unsupported MT3-Infer model: {model}. Use mr_mt3 or yourmt3."
            )
        if not backend_status(self.settings)["music21"]:
            raise TranscriptionEngineUnavailable(
                "MT3-Infer의 MIDI→MusicXML 변환에는 기본 dependency인 music21이 필요합니다."
            )

        checkpoint_root = self._packaged_checkpoint_root() if packaged_runtime() else None
        if packaged_runtime() and checkpoint_root is None:
            raise TranscriptionEngineUnavailable(
                "The packaged MT3-Infer checkpoint is missing or unverified. "
                "Repair the managed transcription runtime in Setup Center; "
                "model auto-download and system checkpoint fallback are disabled."
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
                    # Do not rely solely on Hugging Face offline environment
                    # flags. MT3-Infer itself supports an explicit opt-out
                    # from its default checkpoint auto-download behavior.
                    *(["--no-download"] if checkpoint_root is not None else []),
                ],
                cancel_event=cancel_event,
                env=(
                    {
                        "MT3_CHECKPOINT_DIR": str(checkpoint_root),
                        "HF_HUB_OFFLINE": "1",
                        "TRANSFORMERS_OFFLINE": "1",
                        "HF_DATASETS_OFFLINE": "1",
                        "HF_HUB_DISABLE_TELEMETRY": "1",
                        # The upstream CLI writes Unicode status markers.
                        # Windows redirects the subprocess output to a log,
                        # where legacy console encodings cannot represent them.
                        "PYTHONIOENCODING": "utf-8",
                        "PYTHONUTF8": "1",
                    }
                    if checkpoint_root is not None else None
                ),
            )
            if not midi_path.is_file():
                raise TranscriptionEngineError(
                    f"MT3-Infer did not produce the expected MIDI: {midi_path}"
                )
            midi_to_musicxml(midi_path, musicxml_path)
        except CommandCancelled as exc:
            raise TranscriptionEngineCancelled("MT3-Infer transcription cancelled.") from exc
        except (CommandError, NotationBackendError) as exc:
            raise TranscriptionEngineError(f"MT3-Infer failed.\n{exc}") from exc

        if not musicxml_path.is_file():
            raise TranscriptionEngineError(
                f"MIDI conversion did not create the expected MusicXML: {musicxml_path}"
            )
        return TranscriptionArtifacts(midi_path=midi_path, musicxml_path=musicxml_path)


class MuScriptorEngine(BaseTranscriptionEngine):
    key = "muscriptor"
    display_name = "MuScriptor"
    commercial_status = "noncommercial_weights"
    quality_rank = 1

    def ready(self) -> bool:
        return (
            self.settings.usage_mode != "commercial"
            and command_exists(self.settings.muscriptor_cmd)
            and backend_status(self.settings)["music21"]
            and cached_muscriptor_checkpoint(self.settings.muscriptor_model) is not None
        )

    def describe(self) -> dict[str, object]:
        return {
            **super().describe(),
            "model": self.settings.muscriptor_model,
            "quality_note": "현재 개인/비상업용 정확도 우선 기본값",
            "license_note": "code MIT; public weights CC BY-NC 4.0",
        }

    def transcribe(
        self,
        audio_path: Path,
        output_dir: Path,
        *,
        device: str,
        cancel_event: Event | None = None,
    ) -> TranscriptionArtifacts:
        if self.settings.usage_mode == "commercial":
            raise TranscriptionEngineUnavailable(
                "MuScriptor public weights are CC BY-NC 4.0 and are disabled in commercial mode."
            )
        if not command_exists(self.settings.muscriptor_cmd):
            raise TranscriptionEngineUnavailable("MuScriptor command is unavailable.")
        if not backend_status(self.settings)["music21"]:
            raise TranscriptionEngineUnavailable(
                "MuScriptor MIDI→MusicXML conversion requires embedded music21."
            )
        checkpoint = cached_muscriptor_checkpoint(self.settings.muscriptor_model)
        if checkpoint is None:
            raise TranscriptionEngineUnavailable(
                "MuScriptor checkpoint/config is not complete in the app-managed "
                "Hugging Face cache. Accept the noncommercial license and download "
                "this exact model in Model Manager before running transcription."
            )

        # Upstream --format sheets invokes external MuseScore 4. The desktop
        # contract forbids requiring it: generate the actual MIDI directly,
        # then convert using the embedded music21 backend.
        output_dir.mkdir(parents=True, exist_ok=True)
        midi_path = output_dir / "score.mid"
        musicxml_path = output_dir / "score.musicxml"
        midi_path.unlink(missing_ok=True)
        musicxml_path.unlink(missing_ok=True)
        args = [
            "transcribe", audio_path,
            "--format", "midi",
            "--output", midi_path,
            "--device", device,
            "--model", checkpoint,
            "--detect-tempo", "best-effort",
        ]
        try:
            run_command(
                self.settings.muscriptor_cmd,
                args,
                cancel_event=cancel_event,
                env={
                    "HF_HOME": str(hf_home()),
                    "HF_HUB_OFFLINE": "1",
                    "TRANSFORMERS_OFFLINE": "1",
                    "HF_HUB_DISABLE_TELEMETRY": "1",
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUTF8": "1",
                },
            )
            if not midi_path.is_file() or midi_path.is_symlink():
                raise TranscriptionEngineError(
                    "MuScriptor did not produce a valid score.mid MIDI file."
                )
            # The upstream CLI can succeed with empty or malformed MIDI.
            # Never treat those outputs as a completed multi-instrument score.
            import mido

            try:
                midi = mido.MidiFile(str(midi_path))
            except Exception as exc:
                raise TranscriptionEngineError(
                    "MuScriptor produced an unreadable MIDI file."
                ) from exc
            if not any(
                message.type == "note_on" and message.velocity > 0
                for track in midi.tracks for message in track
            ):
                raise TranscriptionEngineError(
                    "MuScriptor produced MIDI with no performed note events."
                )
            midi_to_musicxml(midi_path, musicxml_path)
        except CommandCancelled as exc:
            raise TranscriptionEngineCancelled("MuScriptor transcription cancelled.") from exc
        except (CommandError, NotationBackendError) as exc:
            raise TranscriptionEngineError(f"MuScriptor failed.\n{exc}") from exc
        if not musicxml_path.is_file() or musicxml_path.is_symlink():
            raise TranscriptionEngineError(
                "The embedded MIDI converter did not produce score.musicxml."
            )
        return TranscriptionArtifacts(midi_path=midi_path, musicxml_path=musicxml_path)


class NativeCommandEngine(BaseTranscriptionEngine):
    key = "native"
    display_name = "AudioScore Native"
    commercial_status = "project_owned"
    quality_rank = 4

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
        MuScriptorEngine(settings),
        MT3InferEngine(settings),
        NativeCommandEngine(settings),
    ]
    return [engine.describe() for engine in engines]


def resolve_transcription_engine(settings: Settings) -> BaseTranscriptionEngine:
    key = settings.transcription_engine.strip().lower()
    if key in {"mt3_infer", "yourmt3"}:
        return MT3InferEngine(settings)
    if key == "muscriptor":
        if settings.usage_mode == "commercial":
            raise TranscriptionEngineUnavailable(
                "MuScriptor cannot be selected in commercial mode because its public weights are CC BY-NC 4.0."
            )
        return MuScriptorEngine(settings)
    if key == "native":
        return NativeCommandEngine(settings)
    raise TranscriptionEngineUnavailable(
        f"Unknown transcription engine: {settings.transcription_engine}"
    )
