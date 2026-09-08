# AudioScoreTool 아키텍처

## 목표

AudioScoreTool은 음원·YouTube·기존 악보를 **Canonical MusicXML**로 통합하고, 곡 단위 SQLite 프로젝트로 저장·검증·편집한 뒤 사용자가 확정한 시점에만 최종 출판 파일을 만드는 local-first 데스크탑 애플리케이션입니다.

핵심 원칙은 다음과 같습니다.

1. **속도보다 최종 악보 품질과 수정량 감소 우선**
2. **SQLite + MusicXML을 편집 상태의 canonical source로 사용**
3. **채보/OMR/직접 import와 export를 분리**
4. **선택 기능의 실패가 핵심 편집 workflow 전체를 막지 않도록 degradation**
5. **LLM은 critic이지 acoustic ground truth가 아님**

## 전체 데이터 흐름

```text
Audio / YouTube ──→ AMT ───────────────┐
                                        │
PDF / Images ─────→ Audiveris OMR ─────┤
                                        ├→ Canonical MusicXML
MusicXML / MXL ───→ Validate/Normalize ─┤
                                        │
MIDI ─────────────→ music21 ────────────┘
                                                ↓
                                      SQLite Song Library
                                  ┌─────────────┼─────────────┐
                                  ↓             ↓             ↓
                              Revisions      Analysis     Publication
                                  └─────────────┼─────────────┘
                                                ↓
                                  OSMD Preview / Inspector Edit
                                                ↓
                              Deterministic Validation + optional LLM
                                                ↓
                                  [사용자: 최종 파일 생성]
                                                ↓
                                  Temporary MusicXML materialization
                                                ↓
                            ┌───────────────────┴──────────────────┐
                            ↓                                      ↓
                   music21 / 자체 처리                   LilyPond + musicxml2ly
                     MIDI / MusicXML                         PDF / Part PDF
```

채보 Job이 끝났다는 이유만으로 PDF나 파트보를 자동 생성하지 않습니다. export는 사용자 의사에 따라 수행되는 별도 단계입니다.

## 데스크탑 구조

```text
Tauri 2 shell
├─ single-instance / native dialogs
├─ bundled Python sidecar lifecycle
├─ dynamic loopback port + runtime API token
├─ updater integration
└─ React + TypeScript + Vite
       ↓ runtime endpoint discovery
FastAPI / Python sidecar
├─ canonical api.py application
├─ SQLite application DB
│  ├─ jobs
│  ├─ songs
│  ├─ song_revisions
│  ├─ song_analysis
│  └─ publication_settings
├─ managed cache / assets / job workspaces
├─ transcription providers
├─ OMR / direct notation ingest
├─ deterministic + optional LLM validation
├─ MusicXML editor/mutation services
└─ explicit export services
```

### Tauri shell

데스크탑 shell, OS 번들링, native folder dialog, single-instance, bundled sidecar lifecycle, updater integration을 담당합니다.

packaged build는 고정 `8080` 포트를 전제로 하지 않습니다. shell이 사용 가능한 loopback port와 API token을 런타임에 준비하고 sidecar에 전달합니다. 개발 환경에서는 별도 개발 endpoint를 사용할 수 있지만, packaged runtime architecture를 문서에서 고정 localhost port로 모델링하지 않습니다.

### FastAPI sidecar

공개 FastAPI application의 단일 owner는 `audio_score_tool.api`입니다. 주요 mutation/ingest endpoint는 method/path 소유자가 명시적으로 등록되어 import order나 compatibility router 조립에 의존하지 않습니다.

sidecar는 다음을 제공합니다.

- job 생성/취소/재시도/조회
- song/revision/publication 저장
- score ingest와 편집
- validation/enrichment
- storage cleanup/recovery
- final export
- startup diagnostics

## 입력 계층

### Audio / YouTube

```text
Input preparation
        ↓
Usage-aware Transcription Policy
├─ personal   → MuScriptor large
│                └─ fallback: YourMT3+ → MR-MT3
└─ commercial → YourMT3+
                 └─ fallback: MR-MT3
        ↓
MIDI + MusicXML
        ↓
선택적 chord / lyric enrichment
```

### PDF / Image OMR

Audiveris를 외부 OMR backend로 사용합니다. 원본 asset을 보존하고 결과 MusicXML은 canonical validation/edit pipeline으로 들어갑니다.

### MusicXML / MXL 직접 import

MusicXML은 크기와 XML 구조를 검증합니다. 위험한 `DOCTYPE`/`ENTITY` 구조를 허용하지 않습니다. MXL은 안전하게 정규화한 뒤 동일한 MusicXML pipeline으로 들어갑니다.

### MIDI 직접 import

music21을 사용해 MusicXML로 변환합니다. 결과는 별도 임시 기능이 아니라 다른 입력과 동일한 Song/Revision/Validation pipeline으로 관리합니다.

## Job과 Song

`Job`은 실행 이력이고 `Song`은 사용자가 장기간 편집·출판하는 프로젝트 객체입니다.

```text
Job
├─ kind / source provenance
├─ queued / running / done / failed / cancelled
├─ input/cache
└─ processing intermediates

Song
├─ original_score_xml
├─ current_score_xml
├─ source_kind
├─ publication_settings
├─ song_revisions
├─ song_analysis
│  ├─ automatic_chords
│  ├─ lyric_alignment
│  └─ validation_report
└─ export state
```

완료된 관련 Job은 incremental ingestion을 통해 Song으로 동기화합니다. 목록 조회가 전체 Job history를 매번 scan하지 않으며, startup/full reconciliation은 복구 경로로 사용합니다. 삭제한 Song이 같은 Job에서 다시 생성되지 않도록 tombstone을 유지합니다.

## 저장 계층

### SQLite canonical state

악보 편집 상태의 단일 기준입니다. MusicXML 본문 자체를 `songs`와 `song_revisions`에 저장합니다.

### Managed cache

OSMD나 외부 notation tool처럼 파일 경로가 필요한 구성요소를 위해 DB MusicXML을 필요할 때 materialize합니다. cache는 삭제되어도 DB에서 재생성할 수 있어야 합니다.

### Managed assets

OMR 원본, MIDI 등 다시 사용할 가치가 있는 비교적 작은 artifact를 앱 데이터 디렉터리에 저장하고 DB가 위치를 관리합니다. 대용량 원본 음원, Demucs stem, model checkpoint를 SQLite BLOB으로 넣지 않습니다.

### Explicit exports

사용자가 `최종 파일 생성`을 실행할 때만 MusicXML/MIDI/PDF/파트보를 생성합니다. Revision이 바뀌면 이전 export state를 stale로 처리합니다.

자세한 내용은 [`STORAGE_V2.ko.md`](STORAGE_V2.ko.md)를 참고하십시오.

## Notation / export backend

MuseScore CLI는 핵심 runtime dependency 또는 fallback이 아닙니다.

| 기능 | 구현 경로 |
|---|---|
| 화면 미리보기 | OpenSheetMusicDisplay |
| MIDI ↔ MusicXML | music21 |
| MusicXML mutation / part 처리 | project-owned Python logic |
| MusicXML → PDF | LilyPond + `musicxml2ly` |
| PDF/Image → MusicXML | Audiveris |

PDF renderer가 없어도 MusicXML/MIDI 중심의 ingest·채보·편집은 계속 동작해야 합니다.

## 검증 계층

### Deterministic validator

MusicXML에서 직접 확인 가능한 구조적 문제를 검사합니다.

- 박자 대비 마디 duration
- 악기 일반 음역 이탈
- rest lyric
- 비정상 tie
- 빈 part

### Optional LLM critic

OpenAI-compatible endpoint를 선택적으로 연결할 수 있습니다. LLM은 bounded symbolic evidence와 결정론적 결과를 바탕으로 검토 우선순위와 이유를 제안합니다.

- 자동 수정 금지
- acoustic correctness 확정 금지
- API key 값 자체는 저장하지 않음
- 원격 endpoint는 HTTPS 정책 적용

## 작업 큐와 복구

Transcription provider, Demucs, WhisperX는 CPU/GPU 메모리를 크게 사용할 수 있으므로 heavy inference는 기본적으로 제한된 concurrency로 실행합니다.

Job lifecycle은 queued/running/done/failed/cancelled/interrupted를 구분하고, startup recovery에서 staged export/upload/job deletion 등 crash residue를 정리·복구합니다. 복구 결과는 startup diagnostics로 노출됩니다.

취소는 UI 상태만 바꾸는 것이 아니라 실행 중 외부 프로세스와 자식 process tree까지 종료해야 합니다.

## 장치 정책

| 환경 | Transcription | Demucs | WhisperX |
|---|---|---|---|
| NVIDIA | CUDA | CUDA | CUDA / FP16 |
| Apple Silicon | provider 지원 범위 내 MPS | CPU | CPU / INT8 |
| CPU | CPU | CPU | CPU / INT8 |

품질이 기본 목표이므로 GPU가 느리다는 이유만으로 자동으로 작은 모델로 downgrade하지 않습니다. 사용자가 Fast/Balanced를 명시적으로 선택할 때만 품질/속도 trade-off를 적용합니다.

## 보안 경계

- sidecar는 loopback interface에만 bind합니다.
- packaged runtime은 API token을 사용합니다.
- mutation 요청에는 origin/token 정책을 적용합니다.
- upload는 size limit과 atomic persistence를 사용합니다.
- XML/archive 입력은 unsafe structure/path traversal을 방지해야 합니다.
- 외부 실행 프로그램에 user input을 shell string으로 직접 결합하지 않습니다.
- updater는 signed metadata/payload 검증을 전제로 stable channel을 구성합니다.

상세 보안 보고 정책은 [`../SECURITY.md`](../SECURITY.md)를 참고하십시오.

## 릴리스 구조

PR CI와 Desktop Packages는 개발/QA 단계입니다. stable release는 다음 신뢰 사슬을 통과해야 합니다.

```text
CI → packaged smoke → unsigned QA artifact
   → Windows signing / macOS signing+notarization
   → checksum + updater signature/manifest
   → clean-install/update acceptance
   → public stable release
```

updater 코드와 release workflow scaffolding은 구현되어 있으며, 실제 인증서/private key provisioning과 signed acceptance는 [Issue #22](https://github.com/JDeun/audio-score-tool/issues/22) 운영 gate입니다.

## 데이터 위치

- macOS: `~/Library/Application Support/AudioScoreTool`
- Windows: `%LOCALAPPDATA%\AudioScoreTool`
- Linux: `$XDG_DATA_HOME/audio-score-tool` 또는 `~/.local/share/audio-score-tool`

기본 DB 이름은 `audio-score-tool.sqlite3`이며 기존 `jobs.sqlite3`가 존재하면 migration 경로를 사용합니다.