# AudioScoreTool 아키텍처

## 목표

AudioScoreTool은 완성된 음원 또는 YouTube URL을 입력으로 받아 다중 악기 악보를 생성하고, 곡 단위로 DB에 저장·편집한 뒤 사용자가 확정한 시점에만 출판 파일을 만드는 로컬 우선 데스크탑 애플리케이션입니다.

## 전체 흐름

```text
Local Audio / YouTube
        ↓
Input preparation
        ↓
Transcription Provider
├─ MR-MT3 (기본)
├─ YourMT3+
├─ MuScriptor (비상업 연구)
└─ AudioScore Native (R&D)
        ↓
MIDI + MusicXML
        ↓
Auto chord analysis
        ↓
MusicXML <harmony>

Audio
  ↓
Demucs (optional)
  ↓
vocals.wav
  ↓
WhisperX
  ↓
word timestamps
  ↓
lyric-note alignment
        ↓
Canonical MusicXML
        ↓
SQLite Song Store
├─ current/original score
├─ revisions
├─ analysis JSON
└─ publication settings
        ↓
OSMD Preview / Inspector Edit
        ↓
DB Revision Commit
        ↓
[사용자: 최종 파일 생성]
        ↓
Temporary MusicXML materialization
        ↓
MuseScore
        ↓
MusicXML / PDF / MIDI / Part Scores
```

채보 Job이 끝났다고 PDF나 파트보를 자동 생성하지 않습니다. PDF/MIDI/파트보는 명시적 Export 단계의 산출물입니다.

## 데스크탑 구조

```text
Tauri 2
├─ native folder dialog
└─ React + TypeScript + Vite
   └─ http://127.0.0.1:8080
      └─ FastAPI / Python sidecar
         ├─ SQLite application DB
         │  ├─ jobs
         │  ├─ songs
         │  ├─ song_revisions
         │  ├─ song_analysis
         │  └─ publication_settings
         ├─ managed cache / assets
         ├─ transcription providers
         ├─ Demucs / WhisperX
         ├─ MusicXML editor
         └─ MuseScore export
```

### Tauri

데스크탑 shell과 OS 번들링을 담당합니다. 릴리스 빌드에서는 PyInstaller로 생성한 Python/FastAPI sidecar를 함께 실행합니다. 최종 Export에서는 Tauri dialog plugin으로 사용자가 실제 저장 폴더를 선택합니다.

### FastAPI sidecar

모델 실행, 작업 큐, 저장공간 관리, 곡 API, 편집 API, DB Revision, Export, 벤치마크를 제공합니다.

## Job과 Song

`Job`은 실행 이력이고 `Song`은 사용자가 장기간 편집·출판하는 프로젝트 객체입니다.

```text
Job
├─ queued/running/done/failed
├─ input/cache
└─ transcription intermediates

Song (SQLite canonical state)
├─ original_score_xml
├─ current_score_xml
├─ publication_settings
├─ song_revisions
├─ song_analysis
└─ export state
```

완료된 transcription Job은 Song으로 동기화됩니다. Song을 삭제한 경우 동일 Job에서 다시 생성되지 않도록 tombstone을 유지합니다.

## 저장 계층

### SQLite

악보 편집 상태의 단일 기준입니다. MusicXML 본문 자체를 `songs`와 `song_revisions`에 저장합니다.

### Managed cache

OSMD 편집 도구나 MuseScore처럼 파일 경로가 필요한 구성요소를 위해 DB MusicXML을 잠시 materialize합니다. 이 파일은 삭제되어도 DB에서 다시 만들 수 있습니다.

### Managed assets

MIDI 등 다시 사용할 가치가 있는 비교적 작은 binary artifact를 앱 데이터 디렉터리에 저장하고 DB가 위치를 관리합니다. 원본 대용량 음원, stem, 모델 checkpoint를 SQLite BLOB으로 넣지는 않습니다.

### Explicit exports

사용자가 `최종 파일 생성`을 실행할 때만 PDF/MIDI/MusicXML/파트보를 생성합니다. 악보 Revision이 바뀌면 앱 내부의 이전 export cache는 무효화합니다.

자세한 내용은 [`STORAGE_V2.ko.md`](STORAGE_V2.ko.md)를 참고하세요.

## 작업 큐

Transcription provider / Demucs / WhisperX는 메모리와 GPU VRAM을 크게 사용할 수 있으므로 heavy inference는 기본적으로 하나씩 직렬 실행합니다.

대기 중인 Job은 `queued`, 실행 중인 Job은 `running` 상태로 관리됩니다.

## 취소

취소는 UI 상태만 변경하지 않습니다. 실행 중인 외부 프로세스와 그 자식 프로세스 트리를 종료합니다.

- Windows: `taskkill /T /F`
- Unix 계열: process group SIGTERM → 필요 시 SIGKILL

`uvx`가 실제 모델 Python 프로세스를 자식으로 실행해도 종료가 전파되도록 설계했습니다.

## 장치 정책

| 환경 | Transcription | Demucs | WhisperX |
|---|---|---|---|
| NVIDIA | CUDA | CUDA | CUDA / FP16 |
| Apple Silicon | MPS 지원 provider 우선 | CPU | CPU / INT8 |
| CPU | CPU | CPU | CPU / INT8 |

WhisperX는 현재 기본 설정에서 MPS 대신 CPU/CUDA를 사용합니다.

## 실행 파일 탐색

앱은 다음 순서로 외부 도구를 찾습니다.

1. 사용자가 설정 화면에서 저장한 경로
2. 설치된 standalone CLI
3. `uvx` fallback

기본 transcription provider는 `MT3-Infer + MR-MT3`입니다. MuScriptor는 공개 weights의 비상업 조건 때문에 기본 상용 경로가 아닙니다.

## 데이터 위치

- macOS: `~/Library/Application Support/AudioScoreTool`
- Windows: `%LOCALAPPDATA%\AudioScoreTool`
- Linux: `$XDG_DATA_HOME/audio-score-tool` 또는 `~/.local/share/audio-score-tool`

v0.8의 기본 DB 이름은 `audio-score-tool.sqlite3`입니다. 기존 `jobs.sqlite3`는 최초 실행 시 마이그레이션합니다.

## 보안

FastAPI는 `127.0.0.1`에만 바인딩합니다.

변경 요청은 Tauri/개발 origin 또는 Origin이 없는 로컬 클라이언트만 허용하여 외부 웹 페이지가 localhost API에 임의 POST를 보내는 위험을 줄입니다.

Hugging Face token 값은 앱에서 읽어 표시하거나 자체 저장하지 않습니다. 인증 여부만 확인합니다.
