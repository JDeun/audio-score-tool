# AudioScoreTool UI/UX 설계 원칙

## 목표

AudioScoreTool의 화면은 두 가지 사용 문맥을 명확히 분리합니다.

1. **관리 문맥**: 새 악보 생성, 라이브러리, 작업 내역, 성능 비교, 설정
2. **편집 문맥**: 악보를 실제로 보고 수정하고 조판·출판하는 Studio Workspace

관리 화면은 간결한 제품 UI를 사용하고, Studio Workspace는 DAW/notation workstation에 가까운 편집기 문법을 사용합니다. 최종 목표는 기능이 많은 연구용 도구가 아니라 장시간 사용할 수 있는 전문 데스크탑 악보 제작 도구입니다.

## Design tokens

- Body text: 13px
- Control text: 12px
- Caption: 11px
- Page title: 21–27px
- 기본 accent: muted olive green
- 악보 편집 chrome: neutral graphite
- 악보 paper: warm white
- 상태 색상은 ready / warning / error에만 제한적으로 사용

9px 이하 텍스트를 제품 본문 정보에 사용하지 않습니다. 아주 짧은 decorative eyebrow를 제외하면 최소 10–11px 이상을 유지합니다.

## 관리 화면

관리 화면에서는 다음 원칙을 따릅니다.

- 카드 수를 최소화하고 같은 깊이의 정보는 divider와 spacing으로 구분
- glass / backdrop blur는 modal/backdrop 등 실제 계층을 표현할 때만 사용
- hover shadow는 약하게 유지
- 동일한 종류의 control은 동일 높이와 typography 사용
- 상태 pill은 필요한 정보만 표시

## Studio Workspace

Studio Workspace의 시각 우선순위는 다음과 같습니다.

1. 악보 paper
2. 현재 악보/Revision/Export/Zoom command bar
3. Inspector
4. Library

### 중앙 score canvas

- surrounding chrome은 graphite 계열
- MusicXML/OSMD가 생성한 SVG intrinsic page geometry를 유지
- paper는 warm white로 표시
- SVG를 임의 비율로 stretch하지 않음
- 실제 publication setting이 MusicXML에 반영된 뒤 같은 XML을 preview하므로 preview와 PDF가 동일한 canonical layout state를 공유

### Library

Library는 독립 card가 아니라 Studio의 좌측 panel로 취급합니다.

- selection 상태를 명확히 표시
- 곡 제목은 12px 이상
- revision/date는 보조 정보로 표현

### Inspector

Inspector는 우측 panel이며 다음 탭을 유지합니다.

- 노트
- 코드
- 마디·조성
- 레이아웃
- 제목·정보

control text는 12px, label/caption은 11px을 기본으로 합니다.

## Preview와 PDF

AudioScoreTool은 다음 구조를 사용합니다.

```text
Canonical Song / MusicXML
        ├─ OSMD SVG preview
        └─ Verovio + fpdf2 PDF export
```

Publication settings는 canonical MusicXML에 기록합니다. 따라서 preview와 export renderer는 서로 다른 렌더러를 사용하더라도 같은 page layout state를 입력으로 사용해야 합니다.

조판 변경 후에는 반드시 preview를 다시 로드해 최종 PDF와 비교 가능한 상태를 유지합니다.

## Responsive behavior

- 1460px 이하: library와 inspector 폭 축소
- 1180px 이하: inspector를 score 아래 전체 폭으로 이동
- 900px 이하: library → score → inspector 단일 column

좁은 화면에서도 score canvas가 최소 편집 폭을 확보하도록 주변 panel이 먼저 재배치됩니다.

## Dark mode

OS의 `prefers-color-scheme: dark`를 따릅니다.

- navigation, form, inspector, modal chrome은 dark surface 사용
- 악보 paper는 인쇄 결과와의 시각적 대응을 위해 항상 밝은 paper를 유지
- score surrounding canvas는 light/dark 모두 graphite 계열을 유지

## Branding

앱 로고는 단순 음표 문자가 아니라 staff line + audio/score movement를 추상화한 단색 심볼을 사용합니다. 동일한 visual language를 앱 아이콘과 README hero asset으로 확장할 수 있습니다.

## 접근성

- focus-visible outline 유지
- 키보드 navigation을 디자인 효과보다 우선
- dark mode에서도 text/background 대비 유지
- control target은 최소 32–38px 높이를 기본으로 유지
- 색상만으로 상태를 전달하지 않음

## Release validation

UI 변경은 최소 다음 검증을 통과해야 합니다.

- TypeScript typecheck
- frontend production build
- keyboard-only Playwright E2E
- Cargo/Tauri shell check
- Windows/macOS/Linux desktop package build

시각 변경 때문에 기존 기능 contract나 export API를 변경하지 않습니다.
