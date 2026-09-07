# AudioScoreTool 아키텍처

## 목표

AudioScoreTool은 완성된 음원 또는 YouTube URL을 입력으로 받아 다중 악기 악보를 생성하고, 곡 단위로 DB에 저장·편집·검증한 뒤 사용자가 확정한 시점에만 출판 파일을 만드는 로컬 우선 데스크탑 애플리케이션입니다.

핵심 정책은 두 가지입니다.

1. **속도보다 최종 악보 품질 우선**
2. **LLM은 검증 critic이지 acoustic ground truth가 아님**

## 전체 흐름

```text
Local Audio / YouTube
        ↓
Input preparation
        ↓
Usage-aware Transcription Policy
├─ personal   → MuScriptor large (quality first)
│                └─ fallback: YourMT3+ → MR-MT3
└─ commercial → YourMT3+ (quality candidate)
                 └─ fallback: MR-MT3
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
Validation
├─ deterministic score checks
└─ optional OpenAI-compatible LLM critic
        ↓
사용자 확인
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
         ├─ deterministic + LLM validation
         ├─ Demucs / WhisperX
         ├─ MusicXML editor
         └─ MuseScore export
```

### Tauri

데스크탑 shell과 OS 번들링을 담당합니다. 릴리스 빌드에서는 PyInstaller로 생성한 Python/FastAPI sidecar를 함께 실행합니다. 최종 Export에서는 Tauri dialog plugin으로 사용자가 실제 저장 폴더를 선택합니다.

### FastAPI sidecar

모델 실행, 작업 큐, 저장공간 관리, 곡 API, 편집 API, DB Revision, validation, Export, 벤치마크를 제공합니다.

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
│  ├─ automatic_chords
│  ├─ lyric_alignment
│  └─ validation_report
└─ export state
```

완료된 transcription Job은 Song으로 동기화됩니다. Song을 삭제한 경우 동일 Job에서 다시 생성되지 않도록 tombstone을 유지합니다.

## 채보 정책

### Personal / non-commercial

정확도 최우선 경로입니다.

```text
MuScriptor large → YourMT3+ → MR-MT3
```

MuScriptor 공개 weights는 CC BY-NC 4.0이므로 personal mode에서만 허용합니다.

### Commercial

MuScriptor를 실행 단계에서 차단합니다.

```text
YourMT3+ → MR-MT3
```

YourMT3+는 정확도 우선 후보지만 source/checkpoint 라이선스 표기가 서로 달라 상용 배포 전 고정 revision 기준 provenance 검토가 필요합니다. MR-MT3는 MIT 경로가 더 단순한 fallback입니다.

`auto` preset은 `quality`로 해석합니다. Fast/Balanced는 사용자가 명시적으로 선택할 때만 사용합니다.

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

## 검증 계층

### Deterministic

MusicXML에서 직접 확인 가능한 구조적 문제를 먼저 검사합니다.

- 박자 대비 단순 마디 duration
- 악기 일반 음역 이탈
- rest lyric
- 중복 tie
- 빈 part

### LLM critic

OpenAI-compatible endpoint를 선택적으로 연결합니다. LLM은 결정론적 결과와 bounded symbolic analysis만 보고 음악적 이상치의 우선순위와 검토 이유를 제안합니다.

- 자동 수정 금지
- acoustic correctness 확정 금지
- API key 값 자체는 저장하지 않음
- 원격 endpoint는 HTTPS만 허용

장기적으로는 resynthesized score와 원음의 audio-symbol discrepancy를 먼저 계산한 뒤 LLM이 해당 evidence를 설명하는 구조를 목표로 합니다.

자세한 내용은 [`VALIDATION.ko.md`](VALIDATION.ko.md)를 참고하세요.

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
| Apple Silicon | provider 지원 범위 내 MPS | CPU | CPU / INT8 |
| CPU | CPU | CPU | CPU / INT8 |

품질이 기본 목표이므로 GPU가 느리더라도 자동으로 작은 모델로 downgrade하지 않습니다. 사용자가 Fast/Balanced를 명시적으로 선택할 때만 모델 크기를 낮춥니다.

## 실행 파일 탐색

앱은 다음 순서로 외부 도구를 찾습니다.

1. 사용자가 설정 화면에서 저장한 경로
2. 설치된 standalone CLI
3. `uvx` fallback

## 데이터 위치

- macOS: `~/Library/Application Support/AudioScoreTool`
- Windows: `%LOCALAPPDATA%\AudioScoreTool`
- Linux: `$XDG_DATA_HOME/audio-score-tool` 또는 `~/.local/share/audio-score-tool`

v0.8의 기본 DB 이름은 `audio-score-tool.sqlite3`입니다. 기존 `jobs.sqlite3`는 최초 실행 시 마이그레이션합니다.

## 보안

FastAPI는 `127.0.0.1`에만 바인딩합니다.

변경 요청은 Tauri/개발 origin 또는 Origin이 없는 로컬 클라이언트만 허용하여 외부 웹 페이지가 localhost API에 임의 POST를 보내는 위험을 줄입니다.

Hugging Face token 값과 LLM API key 값은 앱 설정 파일에 직접 저장하지 않습니다. LLM은 환경변수 이름만 저장합니다.
