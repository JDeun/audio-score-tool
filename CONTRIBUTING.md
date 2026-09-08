# Contributing to AudioScoreTool

AudioScoreTool에 기여해 주셔서 감사합니다. 이 프로젝트는 음악 변환 정확도뿐 아니라 **데이터 무결성, 재현 가능한 빌드, 라이선스 provenance, 데스크탑 배포 신뢰성**을 같은 수준의 품질 기준으로 취급합니다.

## 먼저 확인할 것

작은 버그 수정과 문서 개선은 바로 Pull Request를 열어도 됩니다. 다음 변경은 구현 전에 Issue에서 범위와 근거를 먼저 정리해 주십시오.

- canonical SQLite schema 또는 migration 변경
- public API method/path 변경
- transcription/OMR/notation backend 교체
- 모델 checkpoint 또는 라이선스 provenance 변경
- signing/updater/release trust chain 변경
- 대규모 UI/정보 구조 변경

## 개발 환경

```bash
git clone https://github.com/JDeun/audio-score-tool.git
cd audio-score-tool
uv sync --extra dev

cd desktop
npm ci
```

Tauri shell까지 개발하려면 Rust toolchain과 플랫폼별 Tauri system dependencies가 추가로 필요합니다. 자세한 내용은 [`docs/INSTALLATION.ko.md`](docs/INSTALLATION.ko.md)를 참조하십시오.

## 브랜치와 커밋

변경 목적이 드러나는 짧은 branch name을 사용합니다.

```text
feat/direct-notation-import
fix/job-recovery
perf/job-ingestion
refactor/api-ownership
docs/release-guide
```

커밋은 가능하면 Conventional Commits 계열을 따릅니다.

```text
feat: ...
fix: ...
test: ...
docs: ...
refactor: ...
perf: ...
chore: ...
```

## 로컬 검증

Python:

```bash
uv lock --check
uv run --frozen ruff check src tests training scripts
uv run --frozen pytest -q
```

Frontend:

```bash
cd desktop
npm ci
npm run build
npm run test:e2e
```

Tauri shell:

```bash
cargo check --locked --manifest-path desktop/src-tauri/Cargo.toml
```

GitHub Actions에서는 동일한 핵심 계약과 Windows/macOS/Linux packaged sidecar 및 desktop package build를 추가로 검증합니다.

## 테스트 원칙

- 버그 수정에는 가능한 한 회귀 테스트를 추가합니다.
- API 변경은 method/path ownership 중복 여부를 검증합니다.
- DB 변경은 migration, idempotency, crash/recovery 경로를 검증합니다.
- accessibility 변경은 keyboard-only 경로를 우선 검증합니다.
- 파일 ingest는 크기 제한, 비정상/악성 입력, atomic write 실패 경로를 고려합니다.
- 모델 품질 변경은 임의 예제 한두 개보다 Golden Set과 제품 KPI를 사용합니다.

## 문서 동기화

코드가 다음 항목을 바꾸면 같은 PR에서 문서도 갱신합니다.

- 지원 입력/출력 형식
- 설치 또는 외부 도구 요구사항
- 저장 구조
- 보안 경계
- 모델/라이선스 provenance
- 릴리스/signing/updater 상태

[`docs/README.md`](docs/README.md)에서 문서 역할을 확인할 수 있습니다.

## 모델과 라이선스

모델 이름이나 공개 checkpoint를 추가할 때는 성능만으로 결정하지 않습니다. 반드시 다음을 확인합니다.

- source repository와 고정 revision
- code license
- checkpoint/weights license
- 상용 사용 가능 여부
- 재배포 가능 여부
- runtime에 포함되는지 외부 다운로드인지

확인되지 않은 provenance를 '상용 사용 가능'으로 단정하지 마십시오. 현재 기준은 [`docs/THIRD_PARTY_LICENSES.ko.md`](docs/THIRD_PARTY_LICENSES.ko.md)에 기록합니다.

## Pull Request 체크리스트

PR 설명에는 최소한 다음을 포함해 주십시오.

- 왜 필요한 변경인지
- 무엇이 달라지는지
- 어떤 테스트를 수행했는지
- 사용자/데이터/릴리스 호환성 영향
- 관련 Issue

PR template가 이 항목을 자동으로 제공합니다.

## 보안 이슈

취약점이나 exploit 가능성이 있는 문제는 일반 Issue에 공격 절차·민감 정보를 공개하지 마십시오. [`SECURITY.md`](SECURITY.md)의 절차를 따릅니다.

## 리뷰 기준

리뷰에서는 특히 다음을 봅니다.

1. 기존 canonical state와 public route 계약을 깨지 않는가
2. 실패/취소/재시작 상황에서 데이터를 손상시키지 않는가
3. 선택 기능이 핵심 workflow 전체를 불필요하게 막지 않는가
4. 검증되지 않은 성능·보안·라이선스·배포 상태를 과장하지 않는가
5. 테스트와 문서가 변경 범위를 충분히 고정하는가

작은 PR, 명확한 책임 경계, 재현 가능한 검증을 선호합니다.