# AudioScoreTool v1 Readiness Program

이 문서는 v1 정식 배포까지 남은 작업을 P0~P3로 고정하고, 기능 추가보다 실제 품질·배포·운영 acceptance를 우선하도록 하는 실행 기준입니다.

## P0 — Real-world music quality

목표: `audio -> publishable score`의 실제 품질을 수치화하고, 엔진 변경이 사람의 수정 비용을 줄이는지 판단합니다.

### P0-1 Tier 2 corpus

저장소에는 저작권 음원을 커밋하지 않습니다. 로컬 또는 private artifact storage에 실제 음원을 두고, 저장소에는 manifest/reference/metric schema만 둡니다.

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

### P0-2 품질 지표

모델 지표와 제품 지표를 분리합니다.

모델 지표:
- note onset precision/recall/F1
- onset MAE
- offset MAE
- instrument-aware F1
- meter accuracy
- first-downbeat error
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

### P0-3 Commercial baseline engine

v1 commercial mode는 기본 엔진을 하나로 고정합니다. 후보를 무한히 추가하지 않습니다.

선정 기준:
1. commercial redistribution/provenance가 고정 가능할 것
2. mixed-audio polyphonic multi-instrument transcription을 지원할 것
3. Tier 2에서 사람의 수정 시간이 가장 낮을 것
4. supported hardware에서 runtime/VRAM acceptance를 만족할 것
5. version/revision/checksum을 release 단위로 고정할 수 있을 것

MuScriptor public weights는 CC BY-NC 제한 때문에 commercial baseline 후보에서 제외하고 개인/비상업 모드에만 유지합니다.

## P1 — Managed runtime delivery

Issue #29의 범위를 실제 artifact publication까지 완료합니다.

필수 대상:
- commercial AMT runtime/model
- YouTube ingest stack
- FFmpeg/ffprobe
- 필요한 JS challenge runtime
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
- license
- provenance/source URL
- redistribution status

Acceptance:
- clean Windows/macOS에서 system PATH fallback 없이 지원 기능 실행
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

원칙:
- P3 기능은 canonical MusicXML/SQLite 계약을 깨지 않음
- optional failure가 core score workflow를 block하지 않음
- P0 benchmark에서 품질 개선 근거 없이 기본 엔진을 교체하지 않음

## 버전 기준

- `0.9.x`: feature-complete beta / unsigned QA
- `1.0.0-rc.N`: P0 Tier 2 + 실제 managed runtime artifact + clean-machine QA 준비 완료
- `1.0.0`: signed/notarized clean-install/update acceptance 완료

버전 표기는 Python package, desktop package, Tauri bundle, README badge에서 동일하게 유지합니다.

## Definition of Done

v1은 다음 조건을 모두 만족해야 합니다.

1. 실제 Tier 2 corpus와 reference/metric schema가 존재한다.
2. commercial baseline AMT engine이 고정되어 있다.
3. 사람이 수정한 양과 publish time을 release report에서 확인할 수 있다.
4. 공식 지원 runtime/component가 app-managed artifact로 배포된다.
5. Windows/macOS clean machine에서 end-to-end flow가 동작한다.
6. signed installer/updater trust chain이 실제 검증된다.
7. 문서와 실제 runtime contract가 일치한다.
8. CI/adversarial/package gates가 모두 green이다.
