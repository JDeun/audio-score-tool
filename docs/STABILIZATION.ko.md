# v0.8 안정화 / 코드리뷰 기록

이 문서는 v0.8 Release Candidate 전환을 위한 안정화 리뷰 결과를 기록합니다.

## 1차 리뷰에서 수정한 고위험 항목

### 1. MusicXML cache 동시성

초기 v0.8 구현은 `SongStoreV2.get()/list()`가 조회 과정에서 canonical MusicXML을 공유 cache 파일에 다시 materialize했습니다. 편집 요청이 같은 파일을 수정 중일 때 백그라운드 조회가 들어오면 아직 commit되지 않은 편집 버퍼를 DB의 이전 내용으로 덮어쓸 가능성이 있었습니다.

수정:

- metadata read를 side-effect free로 변경
- MusicXML materialization은 explicit checkout에서만 수행
- checkout 파일을 곡 + FastAPI worker thread 단위로 격리
- 서로 다른 edit / validation / read 요청이 같은 pre-commit 파일을 공유하지 않음

### 2. OMR provenance

OMR Job이 일반 local audio로 분류될 수 있던 문제를 수정했습니다.

- `job.kind == omr` → `source_kind=omr`
- 기존 잘못 분류된 row는 `original-score.*` managed asset을 기준으로 migration

### 3. source identification fallback

문서상의 정책에는 MusicBrainz fuzzy fallback이 있었지만 실제 source-identification endpoint에서 실행되지 않던 누락을 수정했습니다.

현재 순서:

1. embedded tag
2. ISRC → MusicBrainz exact
3. AcoustID fingerprint
4. MusicBrainz fuzzy title/artist
5. model/user fallback

92% 이상 고신뢰 결과만 자동 적용합니다.

### 4. source identification retry

첫 background identification 요청이 일시적인 네트워크/API 오류로 실패하면 앱 재시작 전까지 재시도하지 않던 문제를 수정했습니다.

- `inFlight`와 `completed` 상태 분리
- 성공한 곡만 session terminal state로 표시
- transient failure는 다음 polling에서 재시도

### 5. advisory validator 의미 일치

LLM/Vision/Audio evidence는 advisory라고 정의되어 있었지만 기존 구현에서는 이들이 `severity=error`를 반환하면 전체 `ok=false`가 될 수 있었습니다.

수정:

- `ok`는 deterministic structural validator만 결정
- optional critic은 `review_required`와 `advisory_issue_count`로 분리
- LLM/Vision/Audio evidence는 자동 수정이나 structural veto를 하지 않음

### 6. Vision model untrusted output

Vision model이 malformed page/confidence/message field를 반환할 경우 전체 검증 API가 500으로 종료될 수 있던 경계를 강화했습니다.

- page safe parsing
- confidence clamp
- issue text 길이 제한
- invalid issue collection 무시

### 7. Audio evidence timebase

Global alignment shift가 존재할 때 discrepancy window의 표시 시간이 원본 음원보다 앞쪽으로 치우칠 수 있던 문제를 수정했습니다.

- positive source shift를 original-audio timebase에 반영
- measure guess도 보정된 시간 사용

### 8. LilyPond export 임시파일

LilyPond intermediate `.ly` 파일이 export tree 안에 생성되어 최종 사용자 폴더로 복사될 수 있었고 동시에 두 export가 같은 work path를 사용할 수 있었습니다.

수정:

- renderer별 unique `TemporaryDirectory`
- intermediate는 final export tree 밖에서 생성
- 완료 후 자동 삭제

## 2차 리뷰에서 추가 수정한 항목

### 9. Lyrics provider 입력/응답 방어

외부 lyrics provider는 신뢰 경계 밖이므로 다음을 추가했습니다.

- URL template은 유효한 HTTP(S) URL인지 검사
- 원격 provider는 HTTPS만 허용
- `{title}`, `{artist}` 외 placeholder는 명시적 오류로 처리
- JSON response 최대 4 MiB
- lyrics 본문 최대 200,000자
- provider의 임의 nested payload를 SQLite에 통째로 저장하지 않고 compact scalar metadata만 보존
- MusicBrainz 실패 요청도 1 req/s limiter를 우회하지 못하도록 request timestamp 갱신

### 10. 모델 cache 삭제 race

기존에는 MuScriptor model download가 진행 중이어도 같은 cache를 삭제할 수 있었습니다.

수정:

- queued/running download variant 삭제 차단
- 현재 선택된 MuScriptor variant 삭제 차단
- cache 삭제 실패를 HTTP 오류로 명시

### 11. 대용량 request guard

오디오/PDF 업로드에 전역 request-size guard를 추가했습니다.

- 기본 최대 2 GiB
- 정상 Tauri/browser multipart 요청은 body parsing 전에 `Content-Length`로 413 처리
- 필요할 때만 `AST_MAX_REQUEST_BYTES`로 상향 가능

이는 인터넷-facing quota가 아니라 잘못 선택한 초대형 로컬 파일이나 비정상 요청으로 인한 디스크/메모리 고갈을 줄이기 위한 안정성 장치입니다.

### 12. 중복 export route 제거

`POST /api/songs/{song_id}/export`가 backend-neutral route와 legacy MuseScore-only route로 동시에 등록되어 있었습니다.

- public route owner를 `notation_export_router` 하나로 제한
- runtime route order와 OpenAPI schema가 다른 handler를 가리킬 수 있던 ambiguity 제거

### 13. packaged sidecar lifecycle

Tauri release build가 Python backend sidecar를 spawn한 뒤 child handle과 event receiver를 즉시 버리던 구조를 수정했습니다.

- `CommandChild`를 managed state로 보관
- stdout/stderr event receiver를 비동기 drain하여 pipe back-pressure 방지
- `RunEvent::Exit`에서 child를 명시적으로 `kill()`
- 앱 종료 후 backend orphan process가 남는 가능성 제거

### 14. 외부 가사 편집 buffer 격리

reference lyrics 적용 결과가 곡별 고정 파일명 `score.reference-lyrics.musicxml`을 공유해 동시 요청 시 worker별 checkout 격리를 우회할 수 있었습니다.

- 해당 request의 checkout 파일 stem을 기반으로 destination 생성
- 동일 곡의 concurrent enrichment가 같은 pre-commit output을 공유하지 않음

### 15. UI/version drift

sidebar가 여전히 `v0.6`을 표시하고 첫 실행 설명이 audio/YouTube 전용 문구로 남아 있었습니다.

- v0.8으로 정렬
- Audio / YouTube / PDF / Image 입력과 optional LLM 정책을 onboarding copy에 반영

## 현재 코드리뷰 평가

### Blocking correctness issue

현재 정적 리뷰에서 확인된 명확한 데이터 손상/정책 위반 경로는 위 항목까지 수정했습니다.

다만 실제 Python/TypeScript/Rust test suite는 GitHub-hosted runner가 step 실행 전에 차단되는 외부 계정 상태 때문에 아직 CI로 실행되지 않았습니다. 따라서 `CI green`이나 `Release verified`로 표기하면 안 됩니다.

## Release blocker

### 1. Dependency lockfile

현재 저장소에는 다음 lockfile이 없습니다.

- `uv.lock`
- `desktop/package-lock.json`
- `desktop/src-tauri/Cargo.lock`

따라서 같은 commit이라도 resolver 실행 시점에 따라 다른 dependency version이 설치될 수 있습니다. 정식 installer/release 전에 실제 resolver를 실행해 lockfile을 생성하고 commit해야 합니다.

그 이후 CI는 다음으로 전환합니다.

```text
uv sync --locked
npm ci
cargo check --locked
```

lockfile은 dependency resolver 결과물이므로 내용을 수동으로 추측해 작성하지 않습니다.

### 2. Hosted Actions runner

현재 GitHub-hosted runner는 checkout/echo 이전에 `steps=null`로 종료됩니다. Repository workflow 수정만으로 해제할 수 없는 계정 단위 Actions gate가 남아 있습니다.

이 gate가 해결되면 최소한 다음을 실제 실행해야 합니다.

- ruff
- pytest
- TypeScript/Vite build
- Cargo check
- Windows/macOS/Linux package build

### 3. 실제 E2E / OS QA

최소 release matrix:

- Windows clean install
- macOS clean install
- audio local file
- YouTube import
- Korean / English lyrics
- MuScriptor Large
- commercial MT3 path
- PDF OMR / image OMR
- MusicXML edit / revision / undo
- LilyPond PDF export
- part export
- LLM disabled
- hosted OpenAI-compatible LLM
- source identification with/without external API keys

## RC 이후 강화 항목

다음은 현재 단일 사용자 desktop workflow에서는 blocker로 보지 않지만 v1.0 전에 강화할 가치가 있습니다.

- 동일 곡에 대한 두 개의 실제 mutation request가 동시에 들어올 때 DB revision compare-and-swap
- score edit + title/artist metadata를 하나의 SQLite transaction으로 묶기
- LLM/Vision/Lyrics 공통 HTTP client 도입: bounded response + API-key request의 cross-origin redirect 차단
- chunked request까지 포함한 streaming body-size enforcement와 업로드 전 free-space guard
- 모델 download/auth background job pruning 및 cancellation
- 5,000 Job 전체 scan 대신 incremental Song ingestion
- lockfile 기반 dependency update automation
- signed Windows installer / macOS notarization

## 릴리스 판정 규칙

v0.8 RC는 다음 조건을 모두 만족할 때 `release-ready`로 봅니다.

```text
고위험 정적 리뷰 이슈 = 0
+ 전체 test/build 실제 실행 성공
+ lockfile 3종 commit
+ clean-install E2E 통과
+ installer/signing 정책 확정
```
