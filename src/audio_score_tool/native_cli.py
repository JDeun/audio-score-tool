from __future__ import annotations

import os
import shutil
from pathlib import Path

import typer

from .native_audio import load_log_mel
from .native_events import tokens_to_midi
from .native_model import load_checkpoint
from .runner import CommandError, run_command

app = typer.Typer(help="AudioScore Native multi-instrument transcription runtime.")


def _resolve_musescore() -> str | None:
    configured = os.getenv("AST_MUSESCORE_CMD")
    if configured:
        return configured
    for candidate in ("mscore", "musescore", "MuseScore4", "musescore4", "MuseScore"):
        found = shutil.which(candidate)
        if found:
            return found
    candidate = Path("/Applications/MuseScore 4.app/Contents/MacOS/mscore")
    return str(candidate) if candidate.is_file() else None


def _torch_device(requested: str) -> str:
    from .native_model import require_torch

    torch, _nn = require_torch()
    requested = requested.lower()
    if requested.startswith("cuda") and torch.cuda.is_available():
        return requested
    if requested == "mps" and getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


@app.command()
def transcribe(
    audio: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    output: Path = typer.Option(..., "--output", "-o"),
    checkpoint: Path = typer.Option(..., "--checkpoint", exists=True, dir_okay=False),
    device: str = typer.Option("cpu", "--device"),
    max_tokens: int = typer.Option(4096, "--max-tokens", min=32),
) -> None:
    """Transcribe audio with a project-owned AudioScore Native checkpoint."""

    output.mkdir(parents=True, exist_ok=True)
    torch_device = _torch_device(device)
    model, config, metadata = load_checkpoint(checkpoint, torch_device)
    mel = load_log_mel(audio, config, torch_device)
    generated = model.generate(mel, max_tokens=max_tokens)[0].detach().cpu().tolist()

    midi_path = output / "score.mid"
    tokens_to_midi(generated, midi_path)

    musescore = _resolve_musescore()
    if not musescore:
        raise typer.BadParameter(
            "MuseScore 4 is required to quantize the native MIDI result into MusicXML. "
            "Set AST_MUSESCORE_CMD when it is not discoverable on PATH."
        )

    musicxml_path = output / "score.musicxml"
    pdf_path = output / "full_score.pdf"
    try:
        run_command(musescore, ["-o", musicxml_path, midi_path])
        run_command(musescore, ["-o", pdf_path, musicxml_path])
    except CommandError as exc:
        raise typer.Exit(code=2) from exc

    typer.echo(
        f"AudioScore Native complete: {musicxml_path} "
        f"(checkpoint={checkpoint.name}, dataset={metadata.get('dataset', 'unknown')})"
    )


if __name__ == "__main__":
    app()
