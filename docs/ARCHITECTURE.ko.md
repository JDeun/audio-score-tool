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

### 작업별 채보 모델 선택

파일 업로드와 YouTube 입력은 프리셋·직접 선택을 적용한 설정으로 실행 준비를 검사한 뒤, 다음 선택을 Job SQLite에 저장합니다.

- `transcription_engine`: MT3-Infer / MuScriptor / Native 엔진
- `mt3_model`: MT3 작업의 MR-MT3 / YourMT3 모델
- `muscriptor_model`, `whisperx_model`: 작업에서 선택한 모델 크기
- `native_checkpoint_sha256`: Native를 사용할 때만 직접 지정한 체크포인트의 내용 해시

대기 중 기본 설정이 바뀌어도 worker와 재시도는 이 선택을 복원합니다. 실행 명령·경로·토큰은 snapshot에 포함하지 않으며, 현재 설치 상태와 사용 모드·배포판 정책을 다시 검사합니다. 선택한 모델이 제거되었거나 현재 상용 모드/관리형 배포 정책에서 허용되지 않으면 다른 모델로 대체하지 않고 실패합니다. Native 파일은 경로가 바뀌어도 내용이 같으면 사용할 수 있지만, 내용이 바뀌면 기존 작업에 사용할 수 없습니다. 파일 해시는 실행 직전 확인이며 외부 프로세스의 실행 중 파일 교체까지 원자적으로 고정하는 계약은 아닙니다.

이전 버전의 Job에는 엔진 정보가 없으므로 새 컬럼은 `NULL`로 이관하고 UI에 `모델 정보 없음`을 표시합니다. 과거의 MuScriptor 크기 값만으로 실제 엔진을 추정하지 않습니다. 기존 작업을 다시 실행하면 새 시도의 현재 엔진을 명시적으로 기록하며, 과거 실행의 모델 기록을 새로 만들어내지 않습니다. 신규 작업에서 저장된 모델 식별 정보가 손상되었으면 현재 기본값으로 채우지 않습니다.

이 계약은 모델 선택의 일관성에 관한 것입니다. MT3/MuScriptor의 모든 체크포인트 바이트·런타임 버전을 고정하는 연구 provenance나 모델 품질 승인은 별도입니다. 관련 회귀는 `tests/test_job_transcription_identity.py`와 `desktop/e2e/job-model-identity.spec.ts`에서 확인합니다.

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

## 사용자 선택 악보 경로 — 개인용 로컬 제작 (#185)

사용자는 YouTube URL 또는 로컬 음원을 입력한 다음 **전체 악보**, **보컬+코드 Lead Sheet**, **기타+보컬** 중 출력 목적을 고를 수 있습니다. 기존 API 입력의 기본값은 `score_mode=full`이며, 새 요청은 해당 값을 Job SQLite에 저장하고 재시도 시 유지합니다. 작업 완료 후 Canonical Song에는 `score_request` 분석 메타데이터로 사용자가 선택한 악보 유형과 대상 역할을 남깁니다.

- `full`: 기존 전체 믹스 AMT와 canonical MusicXML 처리/출판. 동작 변경 없음
- `lead_sheet`: Demucs 2-stem `vocals`/`no_vocals`를 실제 분리하고 각각 AMT를 실행. 보컬 멜로디의 우선 파트에 반주 추정 코드 심벌을 합성. 코드 추론이 실패하면 코드가 없는 결과를 Lead Sheet로 가장하지 않고 Job 실패 처리
- `guitar_vocal`: **실험적** Demucs `htdemucs_6s`를 실행해 `vocals.wav` 및 `guitar.wav`를 각각 채보한 뒤 MusicXML에 `Voice`/`Guitar` 파트로 조립. 기타 TAB, 스트로크, 정확한 다중 기타 분해 및 출판 품질은 미검증·미지원
- Demucs 실행파일/스템/음표가 없으면 원곡 전체를 선택 파트 악보라고 속이는 대신 명확히 거부. Packaged mode에서는 기존 managed executable 정책을 따르며, 미배포 Demucs가 PATH를 통해 우회 실행되지 않음
- WhisperX가 설치된 경우 이미 분리한 보컬 WAV를 가사 정렬에 재사용하며, 원음/분리 Stem은 사용자의 로컬 Job 경로에만 저장. 외부 서비스로 자동 공개하지 않음

**품질 한계:** 모델이 한 Stem에서 여러 MIDI 악기/파트를 추정할 수 있어, 현재 역할별 가장 많은 음표를 가진 한 파트를 초안으로 선택합니다. 이 규칙은 보컬·기타의 실제 정확성이나 분리 순도를 입증하지 못합니다. 사용자가 음원 내용을 들으며 수정하는 워크플로를 전제로 합니다. Stem 분리, 보컬 pitch F1, 기타 note/리프 F1, 코드 WCSR와 최종 edit-to-publish는 별도 검증해야 합니다 (#34, #184).

**사용자 권한 UX:** 비상업 개인 로컬 작업의 입력 파일·YouTube URL에 저작권 소유 증명 업로드를 요구하지 않습니다. 플랫폼 서비스 사용약관이나 우회 기술, 서드파티 모델·바이너리 자체의 재배포 권리는 독립 문제입니다. 정식 managed separator 공개 아티팩트 승인 및 clean-machine 실행은 #29에서 검증해야 합니다.
