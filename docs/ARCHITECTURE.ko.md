# AudioScoreTool 아키텍처

## 목표

AudioScoreTool은 완성된 음원 또는 YouTube URL을 입력으로 받아 다중 악기 악보를 생성하고, 곡 단위로 저장·편집·출판하는 로컬 우선 데스크탑 애플리케이션입니다.

## 전체 흐름

```text
Local Audio / YouTube
        ↓
Input preparation
        ↓
MuScriptor
 ├─ multi-instrument note events
 ├─ MIDI
 └─ MusicXML
        ↓
Auto chord analysis
        ↓
MusicXML <harmony>

Audio
  ↓
Demucs
  ↓
vocals.wav
  ↓
WhisperX
  ↓
word timestamps
  ↓
lyric-note alignment

Final MusicXML
  ↓
Song Store / Revision
  ↓
OSMD Preview
  ↓
MuseScore Export
```

## 데스크탑 구조

```text
Tauri 2
└─ React + TypeScript + Vite
   └─ http://127.0.0.1:8080
      └─ FastAPI / Python sidecar
         ├─ persistent SQLite job store
         ├─ Song store
         ├─ MuScriptor
         ├─ Demucs
         ├─ WhisperX
         ├─ MusicXML editor
         └─ MuseScore
```

### Tauri

데스크탑 shell과 OS 번들링을 담당합니다. 릴리스 빌드에서는 PyInstaller로 생성한 Python/FastAPI sidecar를 함께 실행합니다.

### FastAPI sidecar

모델 실행, 작업 큐, 저장공간 관리, 곡 API, 편집 API, 벤치마크를 제공합니다.

### Job과 Song

`Job`은 실행 이력이고 `Song`은 사용자가 편집·출판하는 장기 객체입니다.

```text
Job
├─ queued/running/done/failed
├─ input audio
└─ raw artifacts

Song
├─ original MusicXML
├─ current MusicXML
├─ publication settings
├─ revisions
└─ exports
```

완료된 transcription Job은 Song으로 동기화됩니다. Song을 삭제한 경우 동일 Job에서 다시 생성되지 않도록 tombstone을 유지합니다.

## 작업 큐

MuScriptor / Demucs / WhisperX는 메모리와 GPU VRAM을 크게 사용할 수 있으므로 heavy inference는 기본적으로 하나씩 직렬 실행합니다.

대기 중인 Job은 `queued`, 실행 중인 Job은 `running` 상태로 관리됩니다.

## 취소

취소는 UI 상태만 변경하지 않습니다. 실행 중인 외부 프로세스와 그 자식 프로세스 트리를 종료합니다.

- Windows: `taskkill /T /F`
- Unix 계열: process group SIGTERM → 필요 시 SIGKILL

`uvx`가 실제 모델 Python 프로세스를 자식으로 실행해도 종료가 전파되도록 설계했습니다.

## 장치 정책

| 환경 | MuScriptor | Demucs | WhisperX |
|---|---|---|---|
| NVIDIA | CUDA | CUDA | CUDA / FP16 |
| Apple Silicon | MPS | CPU | CPU / INT8 |
| CPU | CPU | CPU | CPU / INT8 |

WhisperX는 현재 MPS 경로 대신 CPU/CUDA를 사용합니다.

## 실행 파일 탐색

앱은 다음 순서로 외부 도구를 찾습니다.

1. 사용자가 설정 화면에서 저장한 경로
2. 설치된 standalone CLI
3. `uvx` fallback

MuScriptor의 플랫폼 fallback:

- Windows + NVIDIA: `uvx --torch-backend=cu128 muscriptor`
- Apple Silicon: `uvx muscriptor`
- Intel Mac: `uvx --python 3.12 muscriptor`

## 데이터 위치

- macOS: `~/Library/Application Support/AudioScoreTool`
- Windows: `%LOCALAPPDATA%\AudioScoreTool`
- Linux: `$XDG_DATA_HOME/audio-score-tool` 또는 `~/.local/share/audio-score-tool`

## 보안

FastAPI는 `127.0.0.1`에만 바인딩합니다.

변경 요청은 Tauri/개발 origin 또는 Origin이 없는 로컬 클라이언트만 허용하여 외부 웹 페이지가 localhost API에 임의 POST를 보내는 위험을 줄입니다.

Hugging Face token 값은 앱에서 읽어 표시하거나 자체 저장하지 않습니다. 인증 여부만 확인합니다.
