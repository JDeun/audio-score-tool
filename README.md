# AudioScoreTool

Local-first desktop **audio → sheet music** transcription built around MuScriptor, with optional vocal isolation, lyric ASR, lyric-to-note alignment, MusicXML/MIDI export, and model A/B benchmarking.

## Architecture

```text
Audio
 ├─ MuScriptor ───────────────→ MIDI / MusicXML / score PDF
 └─ Demucs → vocals.wav
              ↓
           WhisperX
              ↓
      word-level lyric timings
              ↓
      lyric ↔ note alignment
              ↓
      score_with_lyrics.musicxml
              ↓
           MuseScore
              ↓
      score_with_lyrics.pdf
```

Desktop:

```text
Tauri 2
└─ React + TypeScript + Vite
   └─ local FastAPI/Python sidecar
      ├─ persistent SQLite job store
      ├─ MuScriptor
      ├─ Demucs
      ├─ WhisperX
      └─ MuseScore
```

## v0.3 desktop features

- audio drag-and-drop
- Transcribe / Benchmark / History / Setup workspaces
- Auto / Fast / Balanced / Quality model presets
- manual MuScriptor/WhisperX model overrides
- CUDA / Apple MPS / CPU detection
- persistent job history across app restarts
- queued heavy inference (one model job at a time to avoid VRAM contention)
- real cancellation that terminates the full child-process tree
- retry, delete, output-folder reveal, and storage cleanup
- persistent executable-path overrides for GUI launches where shell `PATH` is unavailable
- Hugging Face authentication status without exposing token values
- local disk usage/free-space diagnostics
- JSON/CSV model benchmark reports
- optional reference MIDI metrics: note precision, recall, F1, and onset MAE
- unsigned macOS/Windows/Linux packaging workflow

## Hardware policy

| Hardware | MuScriptor | Demucs | WhisperX |
|---|---|---|---|
| NVIDIA GPU | CUDA | CUDA | CUDA / FP16 |
| Apple Silicon | MPS | CPU | CPU / INT8 |
| CPU-only | CPU | CPU | CPU / INT8 |

WhisperX is intentionally kept on CUDA/CPU rather than MPS in the current policy.

The Auto preset currently resolves to:

- CPU-only → `fast`
- Apple Silicon → `balanced`
- NVIDIA CUDA → `balanced`

Use the built-in benchmark on your target machine before treating this preset as an empirically optimal choice.

## License constraint

AudioScoreTool does **not** redistribute MuScriptor weights.

MuScriptor source code is MIT-licensed, but the published MuScriptor model weights are **CC BY-NC 4.0 (non-commercial)**. Do not ship the current weights in a commercial product unless the upstream license changes or you obtain separate permission.

## What the user must do

These steps depend on the user's account, hardware, or signing identity and therefore cannot be completed by the repository itself:

1. Open the MuScriptor Hugging Face model page and accept the CC BY-NC 4.0 model license.
2. Authenticate Hugging Face locally:

   ```bash
   uvx hf auth login
   ```

   or provide `HF_TOKEN` in the local environment.

3. Install MuseScore 4+.
4. Ensure `uvx` or the individual model CLIs are available. The app prefers installed commands and automatically falls back to `uvx` when possible.
5. Run the built-in benchmark with representative real audio on the target CPU/GPU/Mac.
6. For signed public distribution, provide the appropriate Apple Developer / Windows code-signing credentials.

Everything else in the current application workflow is implemented in the repository.

## MuScriptor runtime behavior

AudioScoreTool follows MuScriptor's current upstream local-run guidance.

If an installed `muscriptor` CLI is not found and `uvx` exists, the app uses `uvx muscriptor`.

Platform-specific fallback:

- Windows + NVIDIA: `uvx --torch-backend=cu128 muscriptor`
- Apple Silicon: `uvx muscriptor`
- Intel Mac: `uvx --python 3.12 muscriptor`

Equivalent `uvx` fallback is also used for Demucs and WhisperX when their standalone CLIs are not available.

The Setup screen lets you override any executable/command path. These paths are stored locally in the AudioScoreTool application-data directory.

## Development setup

Requirements:

- Python 3.10+
- uv / uvx
- Node.js 22+
- Rust toolchain
- MuseScore 4+
- FFmpeg as required by the model tools

Clone:

```bash
git clone https://github.com/JDeun/audio-score-tool.git
cd audio-score-tool
uv sync --extra dev
```

Authenticate MuScriptor weights:

```bash
uvx hf auth login
```

## CLI

Environment check:

```bash
uv run audio-score doctor
```

Run Korean transcription:

```bash
uv run audio-score run song.mp3 --language ko --output outputs
```

Run score-only mode:

```bash
uv run audio-score run song.mp3 --skip-lyrics
```

## Model benchmark

Without reference MIDI:

```bash
uv run audio-score benchmark song.wav --language ko --profile all
```

With Ground Truth MIDI:

```bash
uv run audio-score benchmark song.wav \
  --language ko \
  --profile all \
  --reference-midi reference.mid
```

Profiles:

- `score`: MuScriptor small / medium / large, lyrics disabled
- `lyrics`: balanced / medium-ASR / quality combinations
- `all`: both matrices

Outputs:

```text
benchmark-results/
├── benchmark.json
└── benchmark.csv
```

Recorded fields include:

- model combination
- wall-clock runtime
- success/failure
- lyric attachment ratio
- note precision
- note recall
- note F1
- onset MAE in milliseconds

Reference-based metrics are only populated when a Ground Truth MIDI file is supplied.

## Desktop development

```bash
cd desktop
npm install
npm run desktop:dev
```

This launches the local Python API and the Tauri development window together.

## Desktop build

```bash
uv sync --extra desktop

cd desktop
npm install
npm run desktop:build
```

The build command:

1. generates platform icon assets,
2. creates the Python FastAPI orchestration sidecar with PyInstaller,
3. builds the Tauri desktop bundle.

Model CLIs, MuseScore, and gated model weights intentionally remain external local dependencies.

## Cross-platform package CI

`.github/workflows/desktop-packages.yml` builds unsigned bundles on:

- Windows
- macOS
- Linux

It runs for product PRs, manual dispatch, and version tags. The resulting bundles are uploaded as GitHub Actions artifacts.

Code signing/notarization is intentionally not hard-coded because it requires owner-specific credentials.

## Local API

Start:

```bash
uv run audio-score-api
```

Default:

```text
http://127.0.0.1:8080
```

Main routes:

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/health` | device/tool/system status |
| GET | `/api/setup` | first-run setup state |
| GET | `/api/presets` | model presets |
| GET | `/api/jobs` | persistent history |
| POST | `/api/jobs` | transcription job |
| POST | `/api/benchmarks` | model benchmark job |
| GET | `/api/jobs/{id}` | job status |
| POST | `/api/jobs/{id}/cancel` | cancel queued/running job |
| POST | `/api/jobs/{id}/retry` | rerun saved input |
| POST | `/api/jobs/{id}/reveal` | reveal job folder |
| DELETE | `/api/jobs/{id}` | delete completed job |
| POST | `/api/storage/cleanup` | remove old job data |
| PUT | `/api/settings/tool-paths` | persist executable overrides |

Artifacts:

```text
GET /api/jobs/{id}/files/midi
GET /api/jobs/{id}/files/musicxml
GET /api/jobs/{id}/files/pdf
GET /api/jobs/{id}/files/transcript
GET /api/jobs/{id}/files/benchmark_json
GET /api/jobs/{id}/files/benchmark_csv
```

## Persistent application data

The app stores history/settings in the platform-standard user data location:

- macOS: `~/Library/Application Support/AudioScoreTool`
- Windows: `%LOCALAPPDATA%\AudioScoreTool`
- Linux: `$XDG_DATA_HOME/audio-score-tool` or `~/.local/share/audio-score-tool`

Stored data includes:

- SQLite job metadata
- input audio retained for retry
- stems and transcription artifacts
- benchmark reports
- local executable-path settings

The Setup screen reports current storage usage and can remove old jobs while retaining the latest 30.

## Lyric alignment

Current alignment remains deliberately modular:

1. Demucs isolates vocals.
2. WhisperX produces word timings.
3. Korean Hangul words are expanded into timed syllables.
4. AudioScoreTool selects a vocal-like MusicXML part.
5. Chord tones sharing an onset are collapsed for lyric placement.
6. Lyric tokens are matched monotonically with binary-search nearest-onset lookup.

This is not yet a singing-specific phoneme aligner. Long melismas, rubato, pickup measures, imperfect source separation, and English syllabification can still require manual correction.

The alignment layer is isolated so a dedicated singing/phoneme aligner can replace it later without changing the desktop/API contract.

## Tests

```bash
uv sync --extra dev
uv run ruff check src tests scripts
uv run pytest -q
```

CI also validates:

- React/TypeScript/Vite production build
- Tauri Rust shell
- fixture-driven end-to-end orchestration without downloading gated model weights
- persistent settings/job database behavior
- cancellation
- MIDI reference metrics
- API validation
- local system diagnostics

Real MuScriptor/WhisperX quality evaluation is intentionally left to the target hardware because gated model access and representative audio are user/environment-specific.
