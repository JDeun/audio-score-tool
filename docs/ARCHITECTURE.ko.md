# AudioScoreTool 아키텍처

## 목표

AudioScoreTool은 음원·YouTube·기존 악보를 **Canonical MusicXML**로 통합하고, 곡 단위 SQLite 프로젝트로 저장·검증·편집한 뒤 사용자가 확정한 시점에만 최종 출판 파일을 만드는 local-first 데스크탑 애플리케이션입니다.

일반 사용자 배포의 추가 원칙은 다음입니다.

1. **installer 하나로 핵심 workflow가 동작해야 합니다.**
2. Python/Node/Rust/uv/pip, MuseScore, LilyPond 같은 시스템 프로그램을 사용자에게 요구하지 않습니다.
3. 큰 모델이나 선택 기능의 runtime은 앱이 자체 관리합니다.
4. 선택 기능의 부재가 핵심 편집·출판 workflow를 막지 않습니다.
5. SQLite + MusicXML을 편집 상태의 canonical source로 사용합니다.
6. LLM은 critic이지 acoustic ground truth가 아닙니다.

세부 dependency 계약은 [`DEPENDENCIES.ko.md`](DEPENDENCIES.ko.md)를 참조하십시오.

## 전체 데이터 흐름

```text
Audio / YouTube ──→ AMT ───────────────┐
                                        │
PDF / Images ─────→ OMR ───────────────┤
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
                          ┌─────────────────────┼─────────────────────┐
                          ↓                     ↓                     ↓
                      music21             자체 MusicXML       Verovio + fpdf2
                        MIDI              MusicXML/parts        PDF / Part PDF
```

Job 완료 시 PDF나 파트보를 자동 생성하지 않습니다. export는 사용자 의사에 따라 수행되는 별도 단계입니다.

## 데스크탑 구조

```text
Tauri 2 shell
├─ single-instance / native dialogs
├─ bundled Python sidecar lifecycle
├─ dynamic loopback port + runtime API token
├─ updater integration
└─ React + TypeScript + Vite bundle
   └─ OpenSheetMusicDisplay
             ↓ authenticated local API
FastAPI / packaged Python sidecar
├─ canonical api.py application
├─ SQLite application DB
├─ music21
├─ Verovio + fpdf2
├─ managed cache/assets/job workspaces
├─ transcription provider boundary
├─ OMR/direct notation ingest
├─ deterministic + optional LLM validation
├─ MusicXML editor/mutation services
└─ explicit export services
```

### Tauri shell

OS 번들링, native dialog, single-instance, sidecar lifecycle, updater integration을 담당합니다.

packaged build는 고정 `8080` 포트를 전제로 하지 않습니다. shell이 사용 가능한 loopback port와 API token을 런타임에 준비하고 sidecar에 전달합니다. frontend source가 개발용 `127.0.0.1:8080` origin을 사용하더라도 `main.tsx`의 runtime fetch shim이 packaged Tauri 환경에서 실제 dynamic origin과 token으로 치환합니다.

### FastAPI sidecar

공개 FastAPI application의 단일 owner는 `audio_score_tool.api`입니다. 주요 mutation/ingest endpoint는 method/path 소유자가 명시적으로 등록되어 import order나 compatibility router 조립에 의존하지 않습니다.

sidecar는 다음을 제공합니다.

- job 생성/취소/재시도/조회
- song/revision/publication 저장
- score ingest와 편집
- validation/enrichment
- storage cleanup/recovery
- final MusicXML/MIDI/PDF/part export
- startup diagnostics

Python 자체와 핵심 Python dependencies는 PyInstaller sidecar 안에 포함하는 것이 배포 계약입니다.

## 입력 계층

### Audio

```text
Input preparation
        ↓
Usage-aware Transcription Policy
├─ personal   → allowed quality-first provider
└─ commercial → commercially permitted provider
        ↓
MIDI / MusicXML
        ↓
선택적 chord / lyric enrichment
```

AMT engine과 model은 크기 때문에 installer 본체와 별도 component가 될 수 있지만, stable desktop UX에서 사용자가 `pip`/`uvx`로 직접 설치하는 구조는 허용하지 않습니다. 앱 bundle 또는 app-data 기반 managed-model-runtime으로 제공해야 합니다.

### YouTube

YouTube URL 입력은 audio ingest 앞단의 선택 기능입니다. upstream 변화에 따라 `yt-dlp`, media decoder, JavaScript challenge runtime/ejs 등이 함께 필요할 수 있으므로 단일 executable이 아니라 **하나의 app-managed component stack**으로 취급합니다.

### PDF / Image OMR

현재 Audiveris integration 경계가 존재합니다. stable desktop에서 공식 OMR 지원을 선언하려면 필요한 Audiveris/Java runtime을 앱이 관리하거나 embedded OMR backend로 대체해야 합니다. 시스템 Java/Audiveris 수동 설치는 최종 사용자 계약이 아닙니다.

### MusicXML / MXL 직접 import

MusicXML은 크기와 XML 구조를 검증합니다. 위험한 `DOCTYPE`/`ENTITY` 구조를 허용하지 않습니다. MXL은 안전하게 정규화한 뒤 동일한 MusicXML pipeline으로 들어갑니다.

### MIDI 직접 import

sidecar에 포함된 music21을 사용해 MusicXML로 변환합니다. 결과는 다른 입력과 동일한 Song/Revision/Validation pipeline으로 관리합니다.

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
└─ export state
```

완료된 관련 Job은 incremental ingestion을 통해 Song으로 동기화합니다. startup/full reconciliation은 복구 경로로 사용합니다. 삭제한 Song이 같은 Job에서 다시 생성되지 않도록 tombstone을 유지합니다.

## 저장 계층

### SQLite canonical state

악보 편집 상태의 단일 기준입니다. MusicXML 본문 자체를 `songs`와 `song_revisions`에 저장합니다.

### Managed cache

파일 경로가 필요한 renderer/component를 위해 DB MusicXML을 필요할 때 materialize합니다. cache는 삭제되어도 DB에서 재생성할 수 있어야 합니다.

### Managed assets / components

OMR 원본, MIDI와 같은 managed asset 및 큰 모델/runtime component는 앱 데이터 영역에서 버전·checksum·license metadata와 함께 관리하는 방향을 사용합니다. 대용량 원본 음원, stem, checkpoint를 SQLite BLOB으로 넣지 않습니다.

### Explicit exports

사용자가 `최종 파일 생성`을 실행할 때만 MusicXML/MIDI/PDF/파트보를 생성합니다. Revision이 바뀌면 이전 export state를 stale로 처리합니다.

## Notation / export backend

외부 notation application을 호출하지 않습니다.

| 기능 | 구현 경로 | 전달 방식 |
|---|---|---|
| 화면 미리보기 | OpenSheetMusicDisplay | frontend bundle |
| MIDI ↔ MusicXML | music21 | Python sidecar |
| MusicXML mutation / part 처리 | project-owned Python logic | Python sidecar |
| MusicXML → SVG engraving | Verovio | Python sidecar |
| SVG → vector PDF | fpdf2 | Python sidecar |
| PDF/Image → MusicXML | OMR component | managed optional component |

PDF 경로는 `MusicXML → Verovio SVG pages → fpdf2 multi-page PDF`입니다. MuseScore/LilyPond/`musicxml2ly` fallback은 사용하지 않습니다.

## 검증 계층

### Deterministic validator

- 박자 대비 마디 duration
- 악기 일반 음역 이탈
- rest lyric
- 비정상 tie
- 빈 part

### Optional audio evidence

FFmpeg/FluidSynth/SoundFont 등을 사용한 resynthesis 비교는 선택 기능입니다. stable distribution에서 공식 지원할 경우 관련 native binary는 app-managed component로 제공해야 합니다.

### Optional LLM critic

OpenAI-compatible endpoint를 선택적으로 연결할 수 있습니다.

- 자동 수정 금지
- acoustic correctness 확정 금지
- API key 값 자체는 저장하지 않음
- 원격 endpoint는 HTTPS 정책 적용

## 작업 큐와 복구

Transcription provider, Demucs, WhisperX는 CPU/GPU 메모리를 크게 사용할 수 있으므로 heavy inference는 제한된 concurrency로 실행합니다.

Job lifecycle은 queued/running/done/failed/cancelled/interrupted를 구분하고 startup recovery에서 crash residue를 정리·복구합니다. 외부/managed subprocess를 사용하는 경우 취소는 자식 process tree까지 종료해야 합니다.

## 보안 경계

- sidecar는 loopback interface에만 bind
- packaged runtime API token 사용
- mutation origin/token 정책
- upload size limit + atomic persistence
- XML/archive unsafe structure/path traversal 차단
- user input을 shell string으로 직접 결합하지 않음
- managed component는 고정 version/checksum/provenance 검증을 전제로 함
- updater는 signed metadata/payload 검증을 전제로 stable channel 구성

## 릴리스 구조

```text
CI → packaged smoke → unsigned QA artifact
   → self-contained clean-machine acceptance
   → Windows signing / macOS signing+notarization
   → checksum + updater signature/manifest
   → clean-install/update acceptance
   → public stable release
```

stable release에서는 system Python/Node/Rust, MuseScore/LilyPond, Homebrew/winget 후설치가 없는 깨끗한 환경을 기준으로 검증합니다. signing credential과 signed acceptance는 [Issue #22](https://github.com/JDeun/audio-score-tool/issues/22)에서 추적합니다.

## 데이터 위치

- macOS: `~/Library/Application Support/AudioScoreTool`
- Windows: `%LOCALAPPDATA%\AudioScoreTool`
- Linux: `$XDG_DATA_HOME/audio-score-tool` 또는 `~/.local/share/audio-score-tool`

기본 DB 이름은 `audio-score-tool.sqlite3`이며 기존 `jobs.sqlite3`가 존재하면 migration 경로를 사용합니다.
