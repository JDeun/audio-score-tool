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
