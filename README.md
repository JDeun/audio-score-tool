# AudioScoreTool

Local-first **audio → sheet music** pipeline built around MuScriptor, with optional lyric extraction and note-aligned MusicXML output.

## What v0.1 does

```text
Audio
 ├─ MuScriptor ───────────────→ score.mid / score.musicxml / full_score.pdf
 └─ Demucs → vocals.wav
              ↓
           WhisperX
              ↓
      word-level lyric timings
              ↓
      MusicXML lyric alignment
              ↓
      score_with_lyrics.musicxml
              ↓
           MuseScore
              ↓
      score_with_lyrics.pdf
```

The application automatically chooses compute backends:

| Hardware | MuScriptor | Demucs | WhisperX |
|---|---|---|---|
| NVIDIA GPU | CUDA | CUDA | CUDA / FP16 |
| Apple Silicon | MPS | CPU | CPU / INT8 |
| CPU-only | CPU | CPU | CPU / INT8 |

WhisperX currently documents CUDA/CPU execution rather than MPS, so Apple Silicon intentionally falls back to CPU for the lyric-ASR stage.

## Important license note

AudioScoreTool itself does **not** redistribute MuScriptor weights.

MuScriptor source code is MIT-licensed, but its published model weights are **CC BY-NC 4.0 (non-commercial)**. Before using the local models, accept the relevant MuScriptor model license on Hugging Face and authenticate locally.

Do not assume the current MuScriptor weights are suitable for commercial deployment.

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- FFmpeg
- MuseScore 4+
- MuScriptor
- Demucs
- WhisperX
- Hugging Face authentication for MuScriptor weights

### 1. Install AudioScoreTool

```bash
git clone https://github.com/JDeun/audio-score-tool.git
cd audio-score-tool

uv sync --extra dev
```

### 2. Install model tools

The model tools are intentionally kept outside the application dependency graph because their PyTorch/CUDA requirements can conflict across platforms.

Typical local setup:

```bash
uv tool install muscriptor
uv tool install demucs
uv tool install whisperx
```

If you prefer a shared environment, installing them with pip/uv into that environment also works.

### Windows + NVIDIA

MuScriptor's upstream documentation currently requires an explicit CUDA PyTorch backend when installed/run via uv on Windows. Follow the current MuScriptor installation instructions for your CUDA version.

### 3. Authenticate to Hugging Face

Accept the MuScriptor model license first, then:

```bash
uvx hf auth login
```

or set:

```bash
export HF_TOKEN=hf_...
```

### 4. Configure MuseScore if necessary

If MuseScore is not discoverable on `PATH`, set:

```bash
export AST_MUSESCORE_CMD="/path/to/mscore"
```

macOS example:

```bash
export AST_MUSESCORE_CMD="/Applications/MuseScore 4.app/Contents/MacOS/mscore"
```

## CLI

### Check the environment

```bash
uv run audio-score doctor
```

Example:

```json
{
  "ok": true,
  "missing": [],
  "device_plan": {
    "torch_device": "cuda",
    "muscriptor_device": "cuda",
    "demucs_device": "cuda",
    "whisperx_device": "cuda",
    "whisperx_compute_type": "float16"
  }
}
```

### Run the full pipeline

Korean:

```bash
uv run audio-score run song.mp3 --language ko --output outputs
```

English:

```bash
uv run audio-score run song.mp3 --language en --output outputs
```

Score only, without lyrics:

```bash
uv run audio-score run song.mp3 --skip-lyrics
```

## Output

A full run creates:

```text
outputs/<song>/
├── score/
│   ├── score.mid
│   ├── score.musicxml
│   ├── full_score.pdf
│   └── ...
├── stems/
│   └── .../vocals.wav
├── lyrics/
│   └── vocals.json
├── alignment.json
├── score_with_lyrics.musicxml
└── score_with_lyrics.pdf
```

If AudioScoreTool cannot directly invoke MuseScore for the final lyric-enriched PDF, it still writes `score_with_lyrics.musicxml` and returns MuScriptor's original `full_score.pdf` with a warning.

## Local API

Start:

```bash
uv run audio-score-api
```

Default address:

```text
http://127.0.0.1:8080
```

### Health / device check

```http
GET /api/health
```

### Submit a job

```http
POST /api/jobs
Content-Type: multipart/form-data

file=<audio file>
language=ko
skip_lyrics=false
```

Response:

```json
{
  "job_id": "...",
  "status": "queued"
}
```

### Poll

```http
GET /api/jobs/{job_id}
```

### Download outputs

```text
GET /api/jobs/{job_id}/files/midi
GET /api/jobs/{job_id}/files/musicxml
GET /api/jobs/{job_id}/files/pdf
GET /api/jobs/{job_id}/files/transcript
```

## Configuration

Environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `AST_MUSCRIPTOR_CMD` | `muscriptor` | MuScriptor command |
| `AST_DEMUCS_CMD` | `demucs` | Demucs command |
| `AST_WHISPERX_CMD` | `whisperx` | WhisperX command |
| `AST_MUSESCORE_CMD` | auto | Explicit MuseScore executable |
| `AST_MUSCRIPTOR_MODEL` | `medium` | MuScriptor model size |
| `AST_WHISPERX_MODEL` | `small` | WhisperX ASR model |

See `.env.example`.

## Lyric alignment in v0.1

The current implementation is deliberately modular and conservative:

1. Demucs isolates the vocal stem.
2. WhisperX produces word-level timestamps.
3. Korean Hangul words are split into syllable tokens using equal-duration subdivision.
4. AudioScoreTool looks for an explicit `Voice/Vocal` part in MuScriptor's MusicXML.
5. If there is no explicit vocal part, it selects the score part whose note attacks best match the ASR word starts.
6. Tokens are attached monotonically to note onsets.

This is a functional first version, **not yet singing-specific forced alignment**. Long melismas, English syllabification, pickup measures, tempo changes, rubato, and imperfect vocal separation can require manual correction.

The alignment layer is isolated so it can later be replaced with a phoneme/singing alignment model without changing the API or transcription pipeline.

## Development

```bash
uv sync --extra dev
uv run ruff check src tests
uv run pytest -q
```

## Current scope

v0.1 focuses on:

- local inference
- automatic CUDA/MPS/CPU selection
- full-score transcription
- vocal isolation
- lyric ASR
- lyric-enriched MusicXML
- PDF rendering when MuseScore is callable
- CLI
- local FastAPI API
- deterministic unit tests for device policy and MusicXML lyric insertion

Planned follow-up work includes singing-specific lyric alignment, manual lyric input/correction, progress streaming, persistent job storage, and an interactive score editor.
