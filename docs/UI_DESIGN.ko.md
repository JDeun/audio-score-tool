# AudioScoreTool UI 디자인 방향

## 목표

AudioScoreTool은 일반적인 AI 대시보드보다 **전문 악보 제작 도구**에 가까워 보여야 합니다.

핵심 인상:

- 차분함
- 정밀함
- 출판/편집 도구의 신뢰감
- 음악 소프트웨어이지만 과도하게 화려하지 않음
- 오랜 시간 사용해도 피로하지 않음

제품 화면은 두 문맥을 명확히 구분합니다.

1. **관리 문맥** — 새 악보, 곡 라이브러리, 작업 내역, 성능 비교, 설정
2. **Studio 문맥** — 실제 악보 수정, 조판, 검증, 미리보기, export

관리 화면은 간결한 제품 UI를 사용하고, Studio는 DAW/notation workstation에 가까운 편집기 문법을 사용합니다.

## 시각 컨셉

### Paper + Olive + Graphite

악보 종이와 편집실을 연상시키는 warm-neutral 배경에 저채도 olive green을 포인트로 사용합니다. Studio에서는 악보 paper를 가장 밝게 두고 주변 편집 chrome은 graphite 계열로 낮춥니다.

```text
Background       warm ivory / paper gray
Surface          near-white warm paper
Primary accent   muted olive green
Studio chrome    neutral graphite
Warning          muted amber
Danger           muted brick red
```

AI 제품에서 흔한 보라색/네온/강한 gradient를 주색으로 사용하지 않습니다.

## Typography

제품 본문은 작은 장식성 텍스트보다 장시간 사용 시 가독성을 우선합니다.

```text
Body             13px
Control           12px
Caption           11px
Page title        21~27px
```

9px 이하 텍스트를 제품 본문 정보에 사용하지 않습니다. eyebrow처럼 장식적 성격이 강한 짧은 텍스트만 예외적으로 9~10px을 허용합니다.

## 계층

### 1. Product shell

사이드바와 페이지 header는 시각적 변화가 적고 안정적이어야 합니다.

### 2. Management surface

새 악보, 설정, benchmark 같은 관리 화면은 card를 사용할 수 있지만 같은 깊이의 정보를 무분별하게 card로 감싸지 않습니다. divider와 spacing을 우선합니다.

### 3. Studio Workspace

Studio에서는 다음 우선순위를 사용합니다.

1. 악보 paper
2. 현재 악보 / Revision / Zoom / Export command bar
3. Inspector
4. Library

악보 paper보다 panel chrome, shadow, gradient가 먼저 보이지 않아야 합니다.

### 4. Utilities

Setup Center, Model Manager, Validation, OMR, Export 등은 동일한 modal 언어를 사용합니다.

- 같은 backdrop depth
- 같은 paper/surface 계열
- 같은 border radius 계열
- 같은 heading hierarchy

## Studio Workspace

### Score canvas

- 주변 chrome은 graphite 계열
- MusicXML/OSMD가 생성한 SVG의 intrinsic page geometry를 유지
- paper는 light/dark OS 모두 밝은 종이색을 유지
- SVG를 임의 비율로 stretch하지 않음
- page 단위에서는 page separation과 shadow를 명확히 표시
- continuous 보기에서는 page 간격을 최소화하되 canonical SVG geometry는 바꾸지 않음

### Library panel

Library는 독립 dashboard card가 아니라 Studio의 좌측 panel입니다.

- 곡 제목을 가장 우선
- artist/source를 2차 정보로 표시
- revision/date는 보조 정보
- 현재 선택 상태를 border/background 둘 다 사용해 표시

### Inspector panel

Inspector는 우측 panel입니다.

- 노트
- 코드
- 마디·조성
- 레이아웃
- 제목·정보

Control text는 12px, label/caption은 11px을 기본값으로 유지합니다.

### View controls

Studio에서는 작업 공간을 확보하기 위해 다음 보기 상태를 제공합니다.

- `Library` — 좌측 곡 목록 표시/숨김
- `Inspector` — 우측 편집 panel 표시/숨김
- `Page` — 인쇄 페이지 단위 보기
- `Continuous` — 페이지 간격을 줄인 연속 보기
- `Focus` — 전역 navigation/header를 숨기고 Studio에 집중

보기 상태는 localStorage에 보존하며 score/model state를 unmount하지 않습니다.

## Preview와 PDF

AudioScoreTool의 canonical layout state는 MusicXML입니다.

```text
Canonical Song / MusicXML
        ├─ OSMD SVG preview
        └─ Verovio + fpdf2 PDF export
```

Publication settings는 canonical MusicXML에 기록합니다. Preview와 PDF renderer가 서로 다른 엔진이더라도 동일한 MusicXML layout state를 입력으로 사용해야 합니다.

따라서 조판 변경 후에는 canonical score를 다시 로드해 preview를 갱신하고, 사용자는 같은 page geometry를 기준으로 export 결과를 판단할 수 있어야 합니다.

## Responsive behavior

Studio panel은 중앙 악보 폭을 우선 보존합니다.

- 1460px 이하: Library/Inspector 폭 축소
- 1180px 이하: Inspector를 score 아래 전체 폭으로 이동
- 900px 이하: Library → score → Inspector 단일 column
- 사용자가 Library/Inspector를 수동으로 숨길 수 있음

## Dark mode

OS의 `prefers-color-scheme: dark`를 따릅니다.

- navigation, form, inspector, modal chrome은 dark surface 사용
- score paper는 인쇄 결과와 대응하기 위해 항상 밝은 paper 유지
- score surrounding canvas는 light/dark 모두 graphite 계열 유지

## Branding

앱의 시각 심볼은 단순 음표 문자보다 staff와 audio/score movement를 추상화한 단색 심볼을 사용합니다.

현재 desktop shell에서는 placeholder `♩` 문자를 직접 노출하지 않고 CSS 기반 staff/waveform mark로 표현합니다. 이후 native app icon과 README hero asset도 동일한 visual language로 확장합니다.

## 모델 관리자

Model Manager는 개발자 설정창이 아니라 **Model Library**처럼 보여야 합니다.

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

사용자가 먼저 봐야 하는 것은 다음 역할입니다.

```text
필수
권장
선택
```

기술명은 세부 정보로 표시하고, 먼저 해당 component가 어떤 기능을 제공하는지 설명합니다.

## 애니메이션

애니메이션은 상태 변화와 조작 피드백에만 사용합니다.

- button hover: 100~180ms
- elevation: 미세하게
- progress bar: 부드러운 width transition
- modal: 과도한 spring/bounce 금지

## 접근성

- `focus-visible` outline 유지
- 키보드 navigation을 시각 효과보다 우선
- dark mode에서도 충분한 text/background 대비 유지
- 주요 control은 최소 30~38px 높이 유지
- 색상만으로 상태를 전달하지 않음
- Studio view toggle은 `aria-pressed`로 상태 노출

## 현재 적용된 polish

- body/control/caption typography 상향
- warm paper + olive 관리 화면
- Studio graphite chrome + 밝은 score paper
- Library/Inspector를 dashboard card가 아닌 Studio panel로 재구성
- Page / Continuous 보기
- Library / Inspector 표시 토글
- Focus mode
- OS dark mode
- CSS 기반 staff/waveform brand mark
- 과도한 backdrop blur/shadow 축소
- modal palette 통일
- keyboard focus lifecycle 유지

## v1.0 전 시각 검증

실제 packaged app에서 다음 해상도로 screenshot QA를 수행합니다.

- 1366×768
- 1440×900
- 1920×1080
- macOS Retina 13~14 inch

검증 항목:

- modal clipping
- score canvas 대비
- Library/Inspector hidden state
- Focus mode 복귀 가능성
- Page/Continuous 전환
- 125%/150% Windows scaling
- 긴 한국어 파일명
- 긴 모델/경로 문자열 overflow
- light/dark OS mode
- focus/keyboard navigation

UI 변경은 기존 score/API contract와 export semantics를 바꾸지 않고 수행합니다.
