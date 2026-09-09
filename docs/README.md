# AudioScoreTool Documentation

이 디렉터리는 사용자 가이드, 제품 설계, 엔진/검증, 릴리스 및 유지보수 문서를 역할별로 분리합니다.

## 사용자와 설치

- [`INSTALLATION.ko.md`](INSTALLATION.ko.md) — 설치 계층, self-contained desktop 계약, managed component 정책
- [`DEPENDENCIES.ko.md`](DEPENDENCIES.ko.md) — 내장/앱 관리/계정/외부 서비스 의존성 inventory와 배포 기준
- [`EDITOR.ko.md`](EDITOR.ko.md) — MusicXML 편집기 기능과 편집 계약
- [`UI_DESIGN.ko.md`](UI_DESIGN.ko.md) — 데스크탑 UI/UX 및 최종 미학 설계 계약
- [`OMR.ko.md`](OMR.ko.md) — PDF/이미지 악보 가져오기와 optional OMR component
- [`ENRICHMENT.ko.md`](ENRICHMENT.ko.md) — 코드·가사 등 악보 보강

## 아키텍처와 데이터

- [`ARCHITECTURE.ko.md`](ARCHITECTURE.ko.md) — canonical API, desktop/sidecar, MusicXML 중심 시스템 구조
- [`STORAGE_V2.ko.md`](STORAGE_V2.ko.md) — SQLite canonical state, cache/assets/jobs/exports 정책
- [`SOURCE_IDENTIFICATION.ko.md`](SOURCE_IDENTIFICATION.ko.md) — 입력/출처 식별 정책

## 모델, 품질, 검증

- [`ENGINE_PERFORMANCE.ko.md`](ENGINE_PERFORMANCE.ko.md) — transcription 엔진 선택과 성능 기준
- [`BENCHMARK.ko.md`](BENCHMARK.ko.md) — Golden Set 및 제품 benchmark 설계
- [`VALIDATION.ko.md`](VALIDATION.ko.md) — 결정론적 validator와 선택적 LLM critic
- [`ADVERSARIAL_VALIDATION.ko.md`](ADVERSARIAL_VALIDATION.ko.md) — 입력·DB·프로세스·API·UI 실패 주입 및 release hardening gate
- [`NATIVE_MODEL.ko.md`](NATIVE_MODEL.ko.md) — AudioScore Native 장기 모델 방향

## 릴리스와 라이선스

- [`RELEASE.ko.md`](RELEASE.ko.md) — CI artifacts, self-contained acceptance, signing/notarization, updater, stable release gate
- [`THIRD_PARTY_LICENSES.ko.md`](THIRD_PARTY_LICENSES.ko.md) — 모델·binary·library provenance와 배포 경계

## 유지보수자 문서

- [`STABILIZATION.ko.md`](STABILIZATION.ko.md) — v0.8 안정화 과정과 회귀 방지 맥락
- 루트 [`PROJECT_CONTEXT.md`](../PROJECT_CONTEXT.md) — 프로젝트의 장기 제품/기술 맥락

> 유지보수자 문서는 현재 제품 사용법의 authoritative source가 아닐 수 있습니다. 사용자 동작과 릴리스 상태는 README, 설치/의존성/아키텍처/릴리스 문서를 우선합니다.

## 문서 변경 원칙

코드 변경으로 입력 형식, canonical storage, runtime/component 요구사항, 보안 경계, 릴리스 상태가 달라지면 같은 PR에서 관련 문서를 함께 수정합니다. 일반 사용자가 별도 시스템 프로그램을 설치해야 하는 상태를 self-contained라고 표현하지 않으며, 아직 실제로 검증하지 않은 managed component나 signed release를 완료된 것처럼 문서화하지 않습니다.

`기능 완료`, `회귀 테스트 통과`, `적대적 안정화`, `3-OS packaged acceptance`, `signed stable release`는 서로 다른 상태로 기록합니다.
