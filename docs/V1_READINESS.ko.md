# AudioScoreTool v1 Readiness Program

이 문서는 v1 정식 배포까지 남은 작업을 P0~P3로 고정하고, 기능 추가보다 실제 품질·배포·운영 acceptance를 우선하도록 하는 실행 기준입니다.

## P0 — Real-world music quality

목표: `audio -> publishable score`의 실제 품질을 수치화하고, 엔진 변경이 사람의 수정 비용을 줄이는지 판단합니다.

### P0-1 Tier 2 corpus

저장소에는 저작권 음원을 커밋하지 않습니다. 로컬 또는 private artifact storage에 실제 음원을 두고, 저장소에는 manifest/reference/metric schema와 승인용 metadata evidence만 둡니다.

필수 장르/구조:

- piano solo
- acoustic guitar
- pop/ballad
- rock/full band
- hip-hop/R&B
- choir/SATB
- orchestral/ensemble
- live/noisy recording
- pickup/anacrusis
- meter/tempo change
- rubato/fade-in/non-musical intro

candidate 비교는 `corpus_version` 문자열만 같아서는 안 됩니다. report의 `manifest_sha256`과 ordered case-id `case_fingerprint`가 모두 같아야 합니다.

### P0-2 품질 지표

모델 지표와 제품 지표를 분리합니다.

모델 지표:
- note onset precision/recall/F1
- onset MAE
- offset MAE
- instrument-aware F1
- music-start error
- meter accuracy
- first-downbeat error(해당 case에 downbeat estimator evidence가 있을 때)
- pickup-length MAE
- chord accuracy
- lyrics alignment coverage
- SATB/part reconstruction accuracy

제품 지표:
- manual_note_edits
- manual_chord_edits
- manual_measure_edits
- manual_part_edits
- manual_lyric_edits
- manual_layout_edits
- total_edit_actions
- time_to_publish_seconds
- successful_export

**최상위 KPI는 `time_to_publish_seconds`와 사람이 수정한 총량입니다.**

수정량 집계는 **유효한 사용자 변경 요청 1회 = `total_edit_actions` 1회**를 원칙으로 합니다. 예를 들어 한 PATCH가 음정과 가사 모두를 실제로 바꾸면 `manual_note_edits` 및 `manual_lyric_edits`는 각각 증가하지만, 총 편집 동작 수는 한 번만 증가합니다. Inspector는 변경된 필드만 PATCH하여 변하지 않은 가사를 수정으로 과대 집계하거나 무수정 저장으로 Revision을 늘리지 않습니다. 제목·크레딧 단일 저장(`/credits`)과 제목/아티스트 변경(`/api/songs/{id}`)은 현재 지표의 `manual_layout_edits`로 분류합니다.

데스크톱의 명시적인 `최종 파일 생성`은 `POST /api/songs/{song_id}/export-to`를 사용합니다. Tier 2 opt-in telemetry는 이 호출이 **전체 MusicXML/PDF/MIDI/파트 악보를 선택한 대상 폴더로 성공적으로 복사한 후**에만 `successful_export`와 `time_to_publish_seconds`를 기록합니다. 부분 형식 export, 실패한 복사, 타곡의 작업, 동일 세션의 재출력은 최초 성공한 완료 시각을 변경하지 않습니다.

Release candidate qualification은 일부 case 결과만으로 통과할 수 없습니다.

- 모든 case의 note/instrument/music-start 평가
- 모든 case의 publish-time 측정
- manifest에서 요구한 meter/pickup/part/chord/lyrics/SATB 등 applicable metric 전체 coverage
- 모든 case 최종 export 성공

이 조건이 모두 필요합니다.

### P0-3 Commercial baseline engine

v1 commercial mode는 기본 엔진을 하나로 고정합니다. 후보를 무한히 추가하지 않습니다.

선정 기준:
1. commercial redistribution/provenance가 고정 가능할 것
2. mixed-audio polyphonic multi-instrument transcription을 지원할 것
3. Tier 2에서 사람의 수정 시간이 가장 낮을 것
4. supported hardware에서 runtime/VRAM acceptance를 만족할 것
5. version/revision/checksum을 release 단위로 고정할 수 있을 것

MuScriptor public weights는 CC BY-NC 제한 때문에 commercial baseline 후보에서 제외하고 개인/비상업 모드에만 유지합니다.

Prediction 생성 시점에 engine/model/runtime/artifact identity를 `tier2-provenance.json`으로 고정하고, benchmark runner는 이 provenance를 자동 사용합니다. 평가 단계에서 revision/checksum을 다시 수기 입력하지 않습니다.

최종 승격은 candidate report 최소 2개 → comparison 재계산 → #34 review → `release/v1-quality-approval.json` 순으로 이루어집니다. release gate는 source report와 comparison의 SHA-256 및 재계산 동일성을 다시 검증합니다.

## P1 — Managed runtime delivery

Issue #29의 범위를 실제 artifact publication까지 완료합니다.

필수 대상:
- commercial AMT runtime/model
- YouTube ingest stack: `yt-dlp + Deno + ffmpeg + ffprobe`
- OMR runtime(Audiveris 또는 대체 엔진) 및 필요한 JRE/runtime
- 지원하기로 결정한 optional validation component

각 artifact에는 최소 다음을 고정합니다.
- component id
- semantic/runtime version
- upstream revision
- platform/arch
- download URL
- SHA-256
- archive/install layout
- required tool map
- license
- provenance/source URL
- redistribution status (`approved`)

Core stable targets:
- Windows x86_64
- macOS arm64

Core components:
- `transcription_engine` → `mt3-infer`
- `youtube_runtime` → `yt-dlp`, `deno`, `ffmpeg`, `ffprobe`
- `audiveris` → `audiveris` launcher

Audiveris가 JVM을 distribution 내부에 포함하면 JRE를 별도 AudioScoreTool tool entry로 노출할 필요는 없지만, 해당 JVM의 provenance/license는 artifact evidence에 포함해야 합니다.

Acceptance:
- clean Windows/macOS에서 system PATH fallback 없이 지원 기능 실행
- packaged yt-dlp가 managed Deno 절대 경로를 명시적으로 사용
- checksum mismatch/interrupted install/corrupt archive fail-closed
- 기존 정상 component를 손상시키지 않는 atomic rollback
- Setup Center에서 install/update/remove/recovery 상태 확인

## P2 — Signed release and clean-machine acceptance

Issue #22의 trust chain을 실제로 활성화합니다.

필수:
- Windows Authenticode signing
- macOS Developer ID signing
- notarization + stapling
- Tauri updater signing
- latest.json signature 검증
- Windows/macOS clean install -> launch -> update -> relaunch
- invalid/tampered update 거부
- 한 플랫폼 실패 시 public release publish 차단

정식 stable은 P0/P1/P2가 모두 green일 때만 허용합니다.

`V1 Release Preflight`뿐 아니라 tagged sidecar packaging 경로 자체도 동일한 P0/P1 unified checker를 실행하므로 별도 workflow를 우회해 v1 release artifact를 만들 수 없습니다.

## P3 — Post-v1 feature track

P3는 진행하되 v1 release gate를 방해하지 않도록 별도 트랙으로 관리합니다.

후보:
- 추가 AMT provider/engine experiment
- vision/LLM critic 고도화
- 추가 export/import format
- DAW integration
- collaboration/cloud sync
- mobile/web companion
- streaming/real-time transcription

공통 isolation policy:
- 기본 활성화 금지
- v1 core release blocker 금지
- canonical MusicXML/SQLite 직접 mutation 금지
- importer는 canonical MusicXML로 normalize
- exporter/DAW bridge는 명시적 materialization으로 동작
- cloud/mobile은 local canonical ownership과 conflict handling을 존중
- streaming 연구는 deterministic offline publish path와 분리
- 새 AMT provider는 Tier 2 승인 없이 default 승격 금지

이 정책은 API의 `optional_feature_policy` metadata로도 노출됩니다.

## 버전 기준

- `0.9.x`: feature-complete beta / unsigned QA
- `1.0.0-rc.N`: P0 Tier 2 + 실제 managed runtime artifact + clean-machine QA 준비 완료
- `1.0.0`: signed/notarized clean-install/update acceptance 완료

버전 표기는 Python package, desktop package, Tauri bundle, README badge에서 동일하게 유지합니다.

## Definition of Done

v1은 다음 조건을 모두 만족해야 합니다.

1. 실제 Tier 2 corpus와 MIDI/MusicXML reference가 존재하고 exact manifest identity가 report에 고정된다.
2. Tier 2의 필수/applicable metric과 모든 publish-time 측정이 full coverage를 만족한다.
3. commercial baseline AMT engine/model/runtime/artifact revision이 승인 receipt로 고정된다.
4. 사람이 수정한 양과 publish time을 release report에서 확인할 수 있다.
5. source reports → comparison → #34 approval evidence가 SHA-256으로 결속되어 재검증된다.
6. 공식 지원 AMT/YouTube/OMR runtime이 app-managed artifact로 배포되며 required tool/provenance/redistribution gate를 통과한다.
7. Windows/macOS clean machine에서 end-to-end flow가 system PATH fallback 없이 동작한다.
8. signed installer/updater trust chain이 실제 검증된다.
9. P3 optional feature가 core canonical/release contract를 침범하지 않는다.
10. 문서와 실제 runtime contract가 일치한다.
11. CI/adversarial/package gates가 모두 green이다.

## GitHub 저장소 보호 정책 코드 감사 (#38, 2026-11-05)

`scripts/audit_branch_governance.py`는 보호 규칙의 API 스냅샷에 PR 강제·`verify` CI 요구·최신 브랜치 강제·force push/삭제 방지·관리자 우회 정책이 있는지 **오프라인으로** 검사합니다. 자세한 절차는 [main 보호 정책](BRANCH_GOVERNANCE.ko.md)에서 확인합니다. 저장소 ruleset은 확인 시점에 비어 있었으며 branch protection 조회에는 HTTP 403이 발생했습니다. 따라서 **실제 보호 활성화는 미검증 운영 과제**이고 출시 준비 완료 주장에 포함하지 않습니다.

### App-managed native 실제 기능 인수시험 (P1)

지원 대상의 게시 승인 메타데이터와 SHA-256이 확보된 뒤, `Desktop Packages --require-managed-delivery`는 단순 파일 설치 상태 외에 **인증된 frozen sidecar API의 WAV 업로드 → 실제 AMT Job 완료 → note-on MIDI/MusicXML 다운로드**를 필수 검증합니다. 제품이 선택한 MT3 모델을 사용하며 무모델·무음 MIDI·잘못된 XML·네이티브 실행 실패는 허용하지 않습니다.

동일 시험에서 Audiveris 배포판 **내장 JRE**가 PATH/JAVA_HOME 없이 시작되는지 확인한 뒤, **패키지 백엔드의 12마디 원본 MusicXML 가져오기 → 자체 Verovio/fpdf2 PDF 조판 → 관리형 Audiveris의 실제 PDF OMR Job → 정규 Song 저장 → MusicXML/MIDI/PDF/파트 출력**까지 검증합니다. 이는 실제 OMR 작업을 필수로 실행하는 *조건부 인수시험 코드*이며, 외부 구성요소가 승인·게시되지 않은 현재 실물 배포가 이 검증을 통과한 것은 아닙니다. 데스크톱 설치·업데이트와 모델/OMR 재배포 권한은 별도입니다. 카탈로그/라이선스가 미승인 상태에서는 이 테스트가 정식 v1 통과를 보고할 수 없습니다.

### YouTube URL→Song 실제 기능 배선 및 릴리스 QA

`Desktop Packages --require-managed-delivery`는 승인된 관리형 네 도구의 native CLI 버전만 확인하지 않고, **사람이 소유·처리 권한을 검토한 실제 단일 YouTube 영상**을 인증된 패키지 API로 조회·가져와 **MT3 AMT → MIDI/MusicXML → 정규 Song**까지 확인합니다. 위 검토 JSON은 `YOUTUBE_QA_SOURCE_REVIEW_JSON` Repository Variable에 준비되어야 하며, 없으면 다운로드 이전에 fail closed합니다. 실제 미디어나 원본 권리 문서는 공개 CI artifact로 저장하지 않습니다.

신규 Job의 `source_kind`를 SQLite로 명시 저장해 `Live. 2026.mp3`처럼 점이 포함된 YouTube 영상 제목이 `local`로 오분류되지 않게 했습니다. 이 검증 경로 및 이전 PDF OMR/MT3 인수시험의 **코드**는 CI에서 합성 테스트를 통과해야 하지만, 현재 미승인 모델·배포 artifact의 **실물 출시 인수시험 성공**이라고 표시하지는 않습니다.

### 개인 YouTube 분석 UX와 자동화 release QA 분리 (#155)

일반 `personal` 모드에서는 **모든 링크에 대한 소유권 확약 체크박스를 강제하지 않으며**, UI의 이용약관/저작권 안내는 비차단으로 표시합니다. `commercial`은 명시적 콘텐츠 처리 권한 확인을 요구합니다. 개인 사용이 모든 YouTube 다운로드의 합법성을 자동 보장하는 것은 아니며, 플랫폼의 독립 약관과 영상/권리 제한은 계속 적용됩니다. v1 태그·수동 QA는 #153의 운영자 검토 기록이 없으면 실제 외부 영상을 다운로드하지 않습니다. UI 모드와 서버 모드가 달라도 API의 최종 정책이 적용됩니다.
