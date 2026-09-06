from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from .config import Settings
from .devices import detect_device_plan
from .pipeline import PipelineError, preflight, transcribe

app = typer.Typer(no_args_is_help=True, help="AudioScoreTool — audio to score with aligned lyrics.")


@app.command()
def doctor() -> None:
    """Inspect local model commands and accelerator selection."""
    typer.echo(json.dumps(preflight(Settings()), ensure_ascii=False, indent=2))


@app.command()
def device() -> None:
    """Print the automatically selected compute plan."""
    typer.echo(json.dumps(detect_device_plan().as_dict(), indent=2))


@app.command()
def run(
    audio: Path = typer.Argument(..., exists=True, readable=True),
    output: Path = typer.Option(Path("outputs"), "--output", "-o"),
    language: str | None = typer.Option(None, "--language", "-l", help="ISO language code, e.g. ko/en."),
    skip_lyrics: bool = typer.Option(False, "--skip-lyrics"),
) -> None:
    """Run the full local transcription pipeline."""
    try:
        result = transcribe(
            audio,
            output,
            language=language,
            skip_lyrics=skip_lyrics,
        )
    except PipelineError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
