# AudioScoreTool

AudioScoreTool은 완성된 음원 또는 YouTube 영상을 입력으로 받아 **악보(MusicXML/PDF/MIDI)를 자동 생성하고, 생성된 악보를 곡 단위로 보관·미리보기·수정한 뒤 내보낼 수 있는 로컬 우선(Local-first) 데스크탑 애플리케이션**입니다.

현재 핵심 목표는 다음과 같습니다.

- 완성 음원에서 악기/보컬을 포함한 악보 자동 채보
- 보컬 분리 후 가사 인식 및 노트-가사 정렬
- YouTube URL에서 오디오를 가져와 동일한 채보 파이프라인 실행
- 곡 1건 단위 라이브러리 관리
- MusicXML 기반 악보 미리보기
- 노트 단위 음정/옥타브/반음/가사 수정
- 수정 이력(Revision) 및 Undo
- 현재 수정본 기준 PDF/MIDI/MusicXML 내보내기
- 로컬 GPU/Apple Silicon/CPU 자동 실행 정책
- 모델 조합 A/B 벤치마크

---

## 전체 구조

```text
[입력]
 ├─ 로컬 오디오 파일
 │    WAV / MP3 / FLAC / M4A / AAC / OGG / OPUS / WEBM
 │
 └─ YouTube URL
      ↓
    yt-dlp
      ↓
   best audio

             ↓
        MuScriptor
             ↓
   MIDI / MusicXML / PDF
             ↓

원본 음원 ─→ Demucs ─→ vocals.wav
                         ↓
                      WhisperX
                         ↓
                  가사 + word timing
                         ↓
                  가사 ↔ 노트 정렬
                         ↓
              score_with_lyrics.musicxml
                         ↓
                    Song Library
                         ↓
        미리보기 / 수정 / Revision / Export
```

데스크탑 구성:

```text
Tauri 2
└─ React + TypeScript + Vite
   ├─ Transcribe
   ├─ YouTube Import
   ├─ Benchmark
   ├─ History
   ├─ Setup
   └─ Song Workspace
        ├─ OpenSheetMusicDisplay
        ├─ Note Inspector
        ├─ Revision / Undo
        └─ Export

Python FastAPI sidecar
├─ MuScriptor
├─ Demucs
├─ WhisperX
├─ yt-dlp
├─ MuseScore
├─ SQLite Job Store
└─ SQLite Song Store
```

---

# 주요 기능

## 1. 로컬 오디오 채보

Transcribe 화면에서 오디오 파일을 드래그하거나 선택하면 다음 파이프라인이 실행됩니다.

1. MuScriptor 악보 채보
2. 필요 시 Demucs 보컬 분리
3. WhisperX 가사 인식
4. 노트-가사 정렬
5. MusicXML/PDF/MIDI 생성

품질 프리셋:

- `Auto`
- `Fast`
- `Balanced`
- `Quality`
- `Custom`

Custom에서는 MuScriptor와 WhisperX 모델을 직접 지정할 수 있습니다.

---

## 2. YouTube URL 입력

앱의 `YouTube Import` 기능에서 YouTube URL을 붙여 넣으면:

1. URL 형식 검증
2. 영상 제목/채널/길이 확인
3. yt-dlp로 단일 영상의 최적 오디오 스트림 추출
4. 기존 AudioScoreTool 채보 파이프라인으로 자동 전달

지원 예:

- `youtube.com/watch?v=...`
- `youtu.be/...`
- YouTube Shorts
- YouTube Live
- YouTube Embed
- YouTube Music

재생목록 전체 일괄 처리는 현재 의도적으로 지원하지 않습니다.

AudioScoreTool은 설치된 `yt-dlp`를 우선 사용하고, 없을 경우 `uvx yt-dlp`를 사용할 수 있습니다.

> YouTube 콘텐츠는 사용자가 다운로드 및 처리 권한을 가진 콘텐츠에 대해서만 사용해야 합니다.

---

# 곡 라이브러리와 악보 편집

채보가 완료된 작업은 `Song Workspace`의 곡 라이브러리에 자동 등록됩니다.

기존 Job은 실행 이력이고, Song은 사용자가 실제로 관리하는 음악 단위입니다.

```text
Job
 └─ 채보 실행 1회

Song
 ├─ 곡 제목
 ├─ 아티스트/메모
 ├─ 원본 MusicXML
 ├─ 현재 수정 MusicXML
 ├─ Revision
 ├─ 수정 백업
 └─ Export 결과
```

## 악보 미리보기

MusicXML은 OpenSheetMusicDisplay(OSMD)를 통해 앱 내부에서 SVG 악보로 직접 렌더링됩니다.

따라서 수정한 뒤 다시 PDF를 생성하지 않아도 현재 MusicXML 상태를 즉시 확인할 수 있습니다.

## 현재 지원하는 수정

노트 단위 Inspector에서 다음을 수정할 수 있습니다.

- 음 이름: A-G
- 반음: ♭♭ / ♭ / ♮ / ♯ / ♯♯
- 옥타브
- 해당 노트의 가사
- 곡 제목
- 아티스트/메모

현재 리듬 길이, 쉼표 추가/삭제, 마디 추가/삭제, 조표/박자표 편집은 구조상 확장 가능하지만 아직 GUI 편집 기능으로 제공하지 않습니다.

## Revision

MusicXML을 수정하기 전에 현재 상태가 revision 파일로 자동 백업됩니다.

예:

```text
songs/<song-id>/
├── original.musicxml
├── score.musicxml
├── revisions/
│   ├── rev-0001.musicxml
│   ├── rev-0002.musicxml
│   └── ...
└── exports/
```

지원 동작:

- 이전 수정 취소(Undo)
- 원본 복원
- 현재 revision 표시

## 내보내기

`현재 악보 내보내기`를 실행하면 **현재 수정 중인 MusicXML을 기준으로** MuseScore가 다시 렌더링합니다.

생성:

- MusicXML
- PDF
- MIDI

즉 최초 AI 채보 결과가 아니라 사용자가 수정한 최종 악보가 export 대상입니다.

---

# 하드웨어 실행 정책

| 환경 | MuScriptor | Demucs | WhisperX |
|---|---|---|---|
| NVIDIA GPU | CUDA | CUDA | CUDA / FP16 |
| Apple Silicon | MPS | CPU | CPU / INT8 |
| CPU only | CPU | CPU | CPU / INT8 |

현재 WhisperX는 안정성을 위해 Apple MPS 대신 CPU 경로를 사용합니다.

Auto 프리셋 기본값:

- CPU only → `fast`
- Apple Silicon → `balanced`
- NVIDIA CUDA → `balanced`

실제 최적 조합은 앱의 Benchmark 기능으로 확인하는 것이 좋습니다.

---

# 모델 벤치마크

같은 음원을 여러 모델 조합으로 실행해 성능을 비교할 수 있습니다.

지원 지표:

- 실행 시간
- 성공/실패
- 가사 attachment ratio
- Note Precision
- Note Recall
- Note F1
- Onset MAE(ms)

Ground Truth MIDI를 제공하면 reference 기반 지표가 추가됩니다.

프로필:

- `score`: MuScriptor small / medium / large
- `lyrics`: 가사 인식 모델 조합
- `all`: 전체 조합

CLI 예:

```bash
uv run audio-score benchmark song.wav \
  --language ko \
  --profile all \
  --reference-midi reference.mid
```

---

# 설치 요구사항

## 필수

- Python 3.10+
- uv / uvx
- Node.js 22+
- Rust toolchain
- MuseScore 4+
- FFmpeg

모델 실행 도구:

- MuScriptor
- Demucs
- WhisperX
- yt-dlp

각 CLI가 직접 설치되어 있으면 이를 우선 사용하고, 가능한 경우 uvx fallback을 사용합니다.

---

# MuScriptor 모델 사용 준비

AudioScoreTool은 MuScriptor 모델 가중치를 저장소에 포함하지 않습니다.

MuScriptor 모델 페이지에서 라이선스를 수락한 뒤 Hugging Face 인증이 필요합니다.

```bash
uvx hf auth login
```

또는 로컬 환경에 `HF_TOKEN`을 설정할 수 있습니다.

앱은 Hugging Face 인증 여부만 확인하며 토큰 값을 읽거나 화면에 표시하지 않습니다.

---

# 라이선스 주의사항

MuScriptor 소스 코드는 MIT이지만 공개 모델 가중치는 현재 **CC BY-NC 4.0** 조건입니다.

따라서 현재 공개 가중치를 그대로 이용하는 상태에서는 상업적 SaaS 또는 유료 제품 배포에 제약이 있습니다.

상업화 시에는 다음 중 하나가 필요합니다.

- MuScriptor 모델의 별도 상업 라이선스
- 상업 이용 가능한 다른 AMT 모델
- 자체 학습 모델

AudioScoreTool은 이를 고려해 transcription backend를 교체 가능한 구조로 확장할 수 있도록 설계되어 있습니다.

OpenSheetMusicDisplay는 BSD-3-Clause 라이선스입니다.

---

# 개발 환경 구성

```bash
git clone https://github.com/JDeun/audio-score-tool.git
cd audio-score-tool
uv sync --extra dev
```

Hugging Face 인증:

```bash
uvx hf auth login
```

환경 확인:

```bash
uv run audio-score doctor
```

---

# CLI 실행

한국어 가사 포함 채보:

```bash
uv run audio-score run song.mp3 --language ko --output outputs
```

악보만 생성:

```bash
uv run audio-score run song.mp3 --skip-lyrics
```

---

# 데스크탑 개발 실행

```bash
cd desktop
npm install
npm run desktop:dev
```

이 명령은 다음을 함께 실행합니다.

- React/Vite UI
- Tauri desktop shell
- 로컬 FastAPI sidecar

---

# 데스크탑 빌드

```bash
uv sync --extra desktop

cd desktop
npm install
npm run desktop:build
```

빌드 과정:

1. 플랫폼 아이콘 생성
2. FastAPI backend를 PyInstaller sidecar로 패키징
3. Tauri desktop bundle 생성

모델 가중치, MuseScore, 외부 모델 CLI는 앱 bundle에 포함하지 않습니다.

---

# 로컬 API

실행:

```bash
uv run audio-score-api
```

기본 주소:

```text
http://127.0.0.1:8080
```

## Job API

| Method | Route | 설명 |
|---|---|---|
| GET | `/api/health` | 장치/도구/시스템 상태 |
| GET | `/api/setup` | 초기 설정 상태 |
| GET | `/api/jobs` | 작업 이력 |
| POST | `/api/jobs` | 로컬 파일 채보 |
| GET | `/api/jobs/{id}` | 작업 상태 |
| POST | `/api/jobs/{id}/cancel` | 작업 취소 |
| POST | `/api/jobs/{id}/retry` | 재실행 |
| POST | `/api/benchmarks` | A/B 벤치마크 |

## YouTube API

| Method | Route | 설명 |
|---|---|---|
| GET | `/api/sources/youtube/status` | yt-dlp 상태 |
| POST | `/api/sources/youtube/inspect` | 영상 정보 확인 |
| POST | `/api/sources/youtube/jobs` | YouTube 채보 작업 생성 |

## Song API

| Method | Route | 설명 |
|---|---|---|
| GET | `/api/songs` | 곡 라이브러리 |
| GET | `/api/songs/{id}` | 곡 정보 |
| GET | `/api/songs/{id}/score` | 현재 MusicXML |
| GET | `/api/songs/{id}/notes` | 노트 Inspector 데이터 |
| PATCH | `/api/songs/{id}` | 곡 제목/메타데이터 수정 |
| PATCH | `/api/songs/{id}/notes/{note_id}` | 노트/가사 수정 |
| POST | `/api/songs/{id}/undo` | 이전 revision 복구 |
| POST | `/api/songs/{id}/restore` | 원본 악보 복원 |
| POST | `/api/songs/{id}/export` | 현재 수정본 PDF/MIDI 생성 |
| GET | `/api/songs/{id}/files/musicxml` | MusicXML 다운로드 |
| GET | `/api/songs/{id}/files/pdf` | PDF 다운로드 |
| GET | `/api/songs/{id}/files/midi` | MIDI 다운로드 |

---

# 데이터 저장 위치

플랫폼 표준 사용자 데이터 디렉터리를 사용합니다.

- macOS: `~/Library/Application Support/AudioScoreTool`
- Windows: `%LOCALAPPDATA%\AudioScoreTool`
- Linux: `$XDG_DATA_HOME/audio-score-tool` 또는 `~/.local/share/audio-score-tool`

저장되는 내용:

```text
AudioScoreTool/
├── jobs.sqlite3
├── jobs/
│   └── <job-id>/
└── songs/
    └── <song-id>/
        ├── original.musicxml
        ├── score.musicxml
        ├── original.mid
        ├── original.pdf
        ├── revisions/
        └── exports/
```

Job 데이터 정리를 실행해도 Song Workspace로 복사된 곡 악보는 별도 곡 데이터로 유지됩니다.

---

# 테스트

```bash
uv sync --extra dev
uv run ruff check src tests scripts
uv run pytest -q
```

CI에서 확인하는 항목:

- Python lint
- Python unit/API tests
- MusicXML note edit / undo
- Song persistence
- React/TypeScript build
- OpenSheetMusicDisplay 포함 Vite production build
- Tauri Rust shell
- Windows/macOS/Linux desktop package build
- process cancellation
- MIDI reference metrics
- YouTube URL validation

실제 MuScriptor/WhisperX 품질은 gated model access와 대상 하드웨어가 필요하므로 최종 음질/정확도 평가는 사용자 환경의 Benchmark에서 수행해야 합니다.
