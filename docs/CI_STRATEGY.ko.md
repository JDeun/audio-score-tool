# CI 실행 전략 — 개발 검증과 패키징 분리

이 문서는 [#78](https://github.com/JDeun/audio-score-tool/issues/78)의 기능 배선/코드 완성 PR과 [#36](https://github.com/JDeun/audio-score-tool/issues/36)의 출시 과정을 분리하기 위한 실행 계약입니다.

## 1. 일반 Pull Request: 코드 중심 필수 CI

`.github/workflows/ci.yml`은 모든 `main` 대상 PR과 `main` push에 반응합니다.

- **python:** forensic hygiene, 지식/출처 문서 구조 검사, frozen Python lock, Ruff, deterministic music adversarial benchmark, 전체 pytest. 전체 pytest에 adversarial/concurrency 케이스가 포함되므로 PR에서는 3회 별도 반복하지 않습니다.
- **frontend:** Node lockfile 설치, React/TypeScript 프로덕션 빌드, Chromium Playwright 접근성·화면·사용자 흐름 E2E.
- **tauri:** Rust/Tauri shell `cargo check`와 warnings-as-errors Clippy. 일반 PR에서는 `desktop/src-tauri`, desktop `package.json/package-lock.json`, CI workflow 변경 시에만 컴파일합니다. `main`과 수동 CI에서는 실행합니다.
- **verify:** 위 단계 결과를 확인하는 안정된 최종 필수 체크명입니다. 필요하지 않아 Tauri가 생략된 경우만 `skipped`를 허용합니다. Python/프런트엔드 또는 필수 Tauri 검사가 실패·취소·생략되면 `verify`도 실패합니다.

`verify` 이름은 [#38](https://github.com/JDeun/audio-score-tool/issues/38)의 `main` 보호 규칙과 호환되도록 유지합니다. GitHub 관리자 규칙 자체는 이 워크플로 변경만으로 활성화되지 않습니다.

## 2. 보안/의존성 검증은 별도 워크플로

- `python-compatibility-audit.yml`: `pyproject.toml`/`uv.lock` 변경 PR, `main` push, 매주 월요일(UTC), 수동 실행. Python 3.11/3.12 frozen-lock 설치·호환성과 runtime/dev/desktop `pip-audit --strict`.
- `dependency-security.yml`: npm/Rust 잠금/매니페스트 변경 PR, `main` push, 매주 월요일(UTC), 수동 실행. npm 고위험 취약점 및 RustSec `cargo-audit`. 외부 action은 정확한 commit SHA에 고정합니다.

일반 기능 PR의 `verify`가 보안 레지스트리 조회나 `cargo-audit` 설치를 기다리지 않습니다. 단, lockfile을 바꾸는 PR의 별도 감사는 성공을 확인해야 하며, 정기 감사 실패를 무시하고 정식 출시해서는 안 됩니다. 새로 알려진 취약점은 단일 코드 커밋의 CI가 성공했다는 이유로 안전하다고 간주하지 않습니다.

## 3. 패키지 QA는 명시적으로 수행

`desktop-packages.yml`의 트리거는 `workflow_dispatch`(수동) 및 `v*` 태그입니다. 일반 PR에서는 실행하지 않습니다. 수동 검증 시 Windows/macOS/Linux 매트릭스로 PyInstaller sidecar smoke, 번들/설치 파일을 생성합니다. 이 unsigned QA artifact는 공개 서명 릴리스가 아닙니다.

다음 경우 `Desktop Packages`를 수동 실행하여 3-OS 결과를 PR/이슈에 근거로 연결합니다.

- `src-tauri`/sidecar 패키징/구성요소 resolver/runtime dependency 변경
- 배포 파이프라인, 설치·업데이트·서명, 플랫폼 기능 수정
- v1 RC/안정판 전 전체 기기 인수시험

일반 UI/API 수정은 `CI / verify`가 우선이고 매 PR마다 인스톨러를 재생성할 필요는 없습니다. 단, 이 정책은 **stable release에 필요한 3-OS package/clean-machine acceptance를 면제하지 않습니다**.

## 4. 메인 브랜치와 릴리스 게이트

- `main` push는 전체 코드 테스트 외에 별도 의존성 감사를 시작합니다. 반복 스트레스 테스트는 `CI / python`의 `main`/수동 경로에서 3회 실행합니다.
- `v1*` 릴리스 후보의 품질 승인 및 관리형 runtime 검사는 `V1 Release Preflight`, `build_sidecar.py` 및 `Desktop Release`의 별도 fail-closed 계약을 그대로 유지합니다.
- 정식 릴리스 직전에는 최신 코드 CI, 의존성 감사, 3-OS package smoke, 실제 self-contained runtime/권리 검토, signing·notarization·updater 검증을 **모두 별도로 확인**합니다.
- `#29`의 실제 managed AMT/YouTube/OMR component artifact 미게시, `#34`의 real-music 평가, `#22`의 서명/공증은 CI 속도 개선과 별개인 출시 차단 항목입니다.

## 5. 검증 및 회귀 가드

`tests/test_ci_workflow_contracts.py`는 일반 PR 패키징 금지, `verify` 이름·업스트림 실패 전파, 코드 CI 필수 테스트, lockfile 기반/정기 보안 감사 트리거가 유지되는지 검사합니다.

변경된 워크플로의 실행 시간이 개선되었는지는 PR/merge의 실제 GitHub Actions 소요 시간으로 판단합니다. 이 문서가 특정 속도 개선 수치를 보장하지는 않습니다.
