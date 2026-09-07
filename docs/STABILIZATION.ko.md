# v0.8 안정화 / 코드리뷰 기록

이 문서는 AudioScoreTool v0.8 Release Candidate 전환을 위해 수행한 정적 코드리뷰와 안정화 결과를 기록합니다.

> 주의: GitHub-hosted runner가 현재 step 실행 전에 차단되고 있으므로 아래의 회귀 테스트는 **추가된 상태**이지 CI에서 통과가 확인된 상태가 아닙니다.

## 1차 리뷰 — canonical score / validation correctness

### MusicXML 작업파일 동시성
- `SongStoreV2.get()/list()`의 read side effect 제거
- MusicXML materialization을 explicit checkout으로 제한
- 곡 + worker별 working MusicXML 분리
- background read가 편집 중 buffer를 덮는 데이터 손실 경로 제거

### OMR provenance
- OMR Job을 `source_kind=omr`로 보존
- 기존 잘못 분류된 row migration

### source identification
- embedded tag → ISRC → AcoustID → MusicBrainz fuzzy → model/user fallback 구현 일치
- transient failure 후 background retry 가능

### validation 의미 정렬
- `ok`는 deterministic structural validator만 결정
- LLM/Vision/Audio evidence는 `review_required`만 제기
- malformed Vision output 정규화
- Audio evidence global alignment timebase 보정

### LilyPond export
- intermediate `.ly`를 final export 밖의 unique temp directory에서 생성

## 2차 리뷰 — 외부 데이터 / sidecar / resource guard

### 외부 Lyrics/API 입력 방어
- remote provider HTTPS-only
- URL template placeholder 제한
- JSON 응답 4 MiB 상한
- lyrics 200,000자 상한
- 임의 nested provider payload를 SQLite에 그대로 저장하지 않음

### 모델 cache race
- 다운로드 중 cache 삭제 차단
- 현재 선택 모델 삭제 차단

### request-size guard
- 기본 2 GiB
- `Content-Length` 사전 검사
- Content-Length 없는 streamed/chunked body도 누적 byte 기준으로 제한

### public API route ownership
- backend-neutral export와 legacy MuseScore-only export 중복 등록 제거
- OpenAPI/runtime route shadowing 방지

### packaged sidecar lifecycle
- Tauri `CommandChild` managed state
- stdout/stderr event stream drain
- 앱 종료 시 sidecar kill

### reference lyrics buffer 격리
- request별 working MusicXML에 연동된 output 사용

### UI/version drift
- v0.8 표시 및 Audio/YouTube/PDF/Image onboarding 문구 정렬

## 3차 리뷰 — 보안 / concurrency / background lifecycle

### revision compare-and-swap
- checkout revision을 materialized filename에 포함
- commit 시 `WHERE revision=?` CAS
- stale edit가 newer revision을 덮으면 `ConcurrentEditError`

### Undo snapshot 경쟁 상태
- stale edit 실패 cleanup이 성공한 다른 edit의 Undo snapshot을 삭제하지 않도록 보호

### 동일 곡 mutation 직렬화
- `SongMutationSerializationMiddleware`
- 같은 song의 POST/PATCH/DELETE는 순차 처리
- 다른 song은 병렬 처리
- lock pool은 weak-reference 기반으로 장시간 세션에서 누적 방지

### localhost browser-origin 경계
- 기존 base API의 restrictive CORS/Origin guard를 재검증
- 별도 중복 middleware는 제거하여 정책 drift 방지

### 공통 안전 HTTP client
- Lyrics / AcoustID / LLM / Vision 공통 bounded JSON reader
- Authorization 또는 POST body가 있는 cross-origin redirect 차단
- HTTP/HTTPS 기본 port origin 정규화
- malformed redirect port 차단

### 저장된 LLM endpoint 재검증
- 새 UI 입력뿐 아니라 저장값 read 시에도 HTTPS/localhost 정책 강제
- 오래된 비안전 remote HTTP 설정은 optional LLM/Vision을 자동 비활성화

### 모델 download/auth lifecycle
- download/auth cancel endpoint
- process-tree 종료
- cancelled/cancelling 상태
- terminal job history 최대 64개
- 중복 auth session 재사용
- UI에도 cancel/polling 상태 연결

### MXL 방어
- archive member 수 제한
- MusicXML/container/전체 uncompressed size 제한
- DOCTYPE/ENTITY 포함 XML 거부

### atomic upload
- `.uploading` 임시파일 → flush/fsync → rename
- ENOSPC는 507
- 실패 시 partial input cleanup
- Audio/Benchmark/OMR product upload route에 적용

## 4차 리뷰 — 삭제 / 저장공간 / SQLite / export / API contract

### Song 삭제 일관성
기존 순서에서는 publication/tombstone을 먼저 변경하고 canonical Song 삭제가 실패할 경우 반쪽 상태가 남을 수 있었습니다.

수정:
- publication row는 `SongStoreV2.delete()`의 동일 SQLite transaction에서 삭제
- tombstone은 re-ingestion 방지를 위해 먼저 기록하되 canonical 삭제 실패 시 compensation으로 제거
- v0.8 delete route를 단독 public owner로 등록

### storage cleanup에서 미수집 완료곡 보호
- cleanup 전에 완료 Job을 canonical Song DB로 promote
- 성공 Job이 canonical DB에 없는 경우 workspace 삭제 금지
- failed/cancelled Job의 orphan `original-audio` asset만 안전하게 회수

### SQLite runtime
- startup 시 `journal_mode=WAL`
- `busy_timeout=10000`
- `synchronous=NORMAL`
- progress/background read와 score mutation 사이 `database is locked` 가능성 감소

### transactional export publish
- 기존 정상 export를 새 export 시작 시 삭제하지 않음
- 새 tree를 staging에서 완성
- 성공한 뒤에만 managed export tree 교체
- renderer/disk failure 시 이전 정상 export 보존
- ENOSPC를 507로 구분

### desktop export destination
- destination 생성/copy 중 ENOSPC도 507
- 실패한 partial destination 삭제

### Tauri capability 최소권한
- 광범위한 `opener:default` 제거
- Setup/Model Manager가 실제로 사용하는 공식 HTTPS URL만 `opener:allow-open-url` scope에 등록
- sidecar spawn은 기존 특정 bundled binary scope만 유지

### 모델 관리자 frontend/backend contract
- `cancelling`, `cancelled` 상태를 frontend type/polling에 반영
- 모델 다운로드 취소 / HF 인증 취소 UI 연결

### 제목/아티스트 metadata
- 수동 제목 변경 후 metadata write 실패 시 score revision rollback
- title/artist 입력 최대 길이 제한
- v0.8 metadata route를 단독 public owner로 등록

### worker thread start failure
- thread 시작 자체가 실패하면 Job을 영구 `queued`로 남기지 않고 `failed` 기록
- 원본 입력은 retry를 위해 유지

### corrupted historical Job JSON
- 한 row의 malformed `result_json` 때문에 전체 작업 내역이 500이 되지 않도록 `result_corrupt=true`로 격리

### route ownership regression
다음 route가 method/path별 하나만 등록되는지 회귀 테스트 추가:
- `POST /api/jobs`
- `POST /api/benchmarks`
- `POST /api/storage/cleanup`
- `POST /api/songs/{song_id}/export`
- `PATCH /api/songs/{song_id}`
- `DELETE /api/songs/{song_id}`

## 현재 정적 코드리뷰 판정

현재까지 발견된 **명확한 고위험 데이터 손실, stale overwrite, credential redirect, partial upload/export, route shadowing** 경로는 위와 같이 수정했습니다.

다만 정적 리뷰는 실제 실행 검증을 대체하지 않습니다.

## Release blocker

### 1. Dependency lockfile
현재 없음:
- `uv.lock`
- `desktop/package-lock.json`
- `desktop/src-tauri/Cargo.lock`

실제 resolver를 실행한 환경에서 생성·commit한 뒤 CI를 다음처럼 고정해야 합니다.

```text
uv sync --locked
npm ci
cargo check --locked
```

### 2. GitHub-hosted Actions runner
최소 `ubuntu-slim` echo probe도 `steps=null`로 실패했으므로 repository workflow 이전의 계정 단위 hosted-runner gate가 남아 있습니다.

해제 후 반드시 실제 실행:
- ruff
- pytest
- frontend typecheck/build
- Cargo check
- Windows/macOS/Linux package build

### 3. 실제 clean-install E2E
최소 matrix:
- Windows clean install
- macOS clean install
- local audio
- YouTube
- MuScriptor Large
- commercial MT3 path
- Korean/English lyrics
- PDF/Image OMR
- MusicXML edit/revision/undo
- LilyPond full score / part export
- export disk failure recovery
- LLM 완전 OFF
- hosted OpenAI-compatible API
- source identification with/without API credentials
- model download/auth cancel

### 4. 배포 신뢰 체인
- Windows signing
- macOS signing/notarization
- installer update/migration 검증

## v1.0 전에 추가 강화할 가치가 있는 항목

정적 리뷰 기준 RC blocker라기보다 다음 단계 hardening입니다.

- fixed `127.0.0.1:8080` 대신 sidecar/frontend 간 per-launch authenticated channel 또는 dynamic port
- score + publication + metadata를 하나의 명시적 SQLite transaction abstraction으로 통합
- 5,000 Job scan 대신 incremental ingestion cursor/event 방식
- crash-safe export directory swap recovery marker
- orphan cache/backup self-healing startup sweep
- structured/redacted sidecar log와 crash diagnostics

## 릴리스 판정 규칙

```text
고위험 정적 리뷰 이슈 = 0
+ 전체 test/build 실제 실행 성공
+ lockfile 3종 commit
+ clean-install E2E 통과
+ signing/notarization 정책 확정
```

이 조건을 만족하기 전에는 `CI green` 또는 `release verified`라고 표기하지 않습니다.
