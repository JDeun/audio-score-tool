# AudioScoreTool UI 디자인 방향

## 목표

AudioScoreTool은 일반적인 AI 대시보드보다 **전문 악보 제작 도구**에 가까워 보여야 합니다.

핵심 인상:

- 차분함
- 정밀함
- 출판/편집 도구의 신뢰감
- 음악 소프트웨어이지만 과도하게 화려하지 않음
- 오랜 시간 사용해도 피로하지 않음

## 시각 컨셉

### Paper + Olive

악보 종이와 편집실을 연상시키는 warm-neutral 배경에 저채도 olive green을 포인트로 사용합니다.

```text
Background       warm ivory / paper gray
Surface          near-white warm paper
Primary accent   muted olive green
Warning          muted amber
Danger           muted brick red
```

AI 제품에서 흔한 보라색/네온/강한 gradient를 주색으로 사용하지 않습니다.

## 계층

### 1. Product shell

사이드바와 페이지 header는 시각적 변화가 적고 안정적이어야 합니다.

### 2. Work surface

실제 작업 카드와 악보 영역이 가장 밝고 명확하게 보입니다.

### 3. Utilities

Setup Center, Model Manager, Validation, OMR, Export 등은 동일한 modal 언어를 사용합니다.

- 같은 backdrop blur
- 같은 paper surface
- 같은 border radius 계열
- 같은 shadow depth
- 같은 eyebrow / heading hierarchy

## 모델 관리자

Model Manager는 개발자 설정창이 아니라 **Model Library**처럼 보이도록 설계합니다.

각 카드에서 다음을 한눈에 판단할 수 있어야 합니다.

- 모델 이름
- 규모
- 설치 여부
- 현재 선택 여부
- 다운로드 용량
- cache 사용량
- 라이선스

상태 색상만으로 의미를 전달하지 않고 텍스트 label을 함께 제공합니다.

## 설치 경험

설치 UI의 목적은 사용자가 기술적인 dependency graph를 이해하게 만드는 것이 아닙니다.

사용자가 봐야 하는 것은:

```text
필수
권장
선택
```

뿐입니다.

`uv`, `LilyPond`, `Audiveris` 등의 기술명은 세부 정보로 표시하되, 먼저 역할을 설명합니다.

예:

```text
PDF 엔진
출판용 PDF 생성
LilyPond
```

## 애니메이션

애니메이션은 상태 변화와 조작 피드백에만 사용합니다.

- button hover: 100~180ms
- card elevation: 미세하게
- progress bar: 부드러운 width transition
- modal: 과도한 spring/bounce 금지

## Typography

텍스트 위계는 크기보다 weight와 spacing을 우선합니다.

- Page title: 짧고 강한 heading
- Section title: 중간 크기
- Eyebrow: 작은 uppercase, 넓은 tracking
- 설명: 낮은 contrast
- 기술 정보/cache/path: monospace 보조

## 장시간 편집 UX

악보 편집기는 화려함보다 집중이 중요합니다.

- score canvas 주변 contrast를 낮게 유지
- 핵심 toolbar만 명확하게
- 경고/검증 상태는 필요할 때만 강하게
- 불필요한 floating control 증가 금지

현재 여러 utility entry가 존재하므로 장기적으로는 floating button을 계속 추가하기보다 하나의 `Tools` 또는 우측 inspector 영역으로 합치는 것이 적절합니다.

## 현재 적용된 polish

- warm paper 배경 gradient
- sidebar translucency/경계 정리
- card elevation 통일
- input focus ring 통일
- scrollbar 정리
- 버튼 hover/press motion 통일
- Validation/OMR/Export modal palette 통일
- Setup Center / Model Manager를 동일한 visual family로 구성
- floating utility의 vertical spacing 정리

## v1.0 전 시각 검증

실제 packaged app에서 다음 해상도로 screenshot QA를 수행합니다.

- 1366×768
- 1440×900
- 1920×1080
- macOS Retina 13~14 inch

검증 항목:

- modal clipping
- score canvas 대비
- 125%/150% Windows scaling
- 긴 한국어 파일명
- 긴 모델/경로 문자열 overflow
- dark OS chrome과 앱 light UI의 조화
- focus/keyboard navigation

큰 리디자인은 이 QA 결과에서 실제 문제가 확인될 때만 진행합니다.
