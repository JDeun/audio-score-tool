# Security Policy

AudioScoreTool은 로컬 우선 데스크탑 애플리케이션이지만, 업로드 파일 처리, localhost API, 외부 도구 실행, updater와 installer가 보안 경계를 형성합니다.

## 지원 범위

보안 수정은 기본적으로 현재 `main`과 최신 공개 release line을 대상으로 합니다. 아직 signed stable public release가 활성화되지 않은 단계에서는 `main`이 코드 기준의 authoritative source입니다.

## 취약점 보고

보안 취약점이라고 판단되는 문제는 **일반 GitHub Issue에 exploit 절차, 토큰, 민감 파일, 사용자 데이터 또는 재현 가능한 공격 payload를 공개하지 마십시오.**

가능한 경우 이 저장소의 GitHub **Private vulnerability reporting / Security Advisory** 기능을 사용하십시오.

해당 기능을 사용할 수 없는 경우에는 민감한 세부정보 없이 일반 Issue에 "private security contact가 필요하다"는 사실만 남겨 주십시오. 공개 채널에 공격 절차를 게시하지 마십시오.

> 이 문서는 존재하지 않는 이메일 주소나 별도 보안 연락처를 임의로 제시하지 않습니다.

## 보고 시 포함할 정보

비공개 채널에서 다음 정보를 제공하면 분석에 도움이 됩니다.

- 영향을 받는 commit/tag/version
- 운영체제와 설치 형태
- 영향 범위와 전제 조건
- 최소 재현 절차
- 실제 또는 잠재 영향
- 가능하면 완화 방법 제안

민감 정보와 실제 사용자 데이터는 필요한 최소 범위만 공유하십시오.

## 주요 보안 경계

### Local API

- packaged desktop backend는 loopback interface에서만 수신해야 합니다.
- mutation endpoint는 API token/origin 정책을 우회해서는 안 됩니다.
- 동적 runtime port를 외부 인터페이스에 노출하지 않습니다.

### 파일 ingest

- 업로드 크기 제한을 유지합니다.
- partial file은 atomic write/staging 정책을 사용합니다.
- XML 계열 입력은 외부 entity/DOCTYPE 등 위험한 구조를 허용하지 않습니다.
- ZIP/MXL 등 archive 입력은 path traversal과 비정상 압축 구조를 고려합니다.

### 외부 실행 프로그램

LilyPond, Audiveris 등 외부 도구를 실행할 때 사용자 입력을 shell command string으로 직접 결합하지 않습니다. 실행 파일 경로와 인자는 명시적으로 분리하고, 임시 작업 경로의 생명주기를 관리합니다.

### Desktop updater

- unsigned QA artifact와 stable release를 구분합니다.
- updater manifest와 payload signature 검증을 우회하지 않습니다.
- 한 플랫폼의 signing/notarization 실패 시 해당 artifact를 정상 stable release로 홍보하지 않습니다.
- update 실패가 기존 설치를 손상시키지 않아야 합니다.

실제 signed release activation은 [Issue #22](https://github.com/JDeun/audio-score-tool/issues/22)에서 추적합니다.

## 공개 시점

취약점은 수정과 배포 전략이 준비된 뒤 coordinated disclosure 방식으로 공개하는 것을 원칙으로 합니다. 보안 수정이 포함된 PR/Issue 제목과 설명에서도 필요한 경우 세부 공격 방법을 제한합니다.