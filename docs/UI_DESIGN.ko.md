# AudioScoreTool UI/UX 디자인 시스템

## 1. 제품 시각 목표

AudioScoreTool은 일반적인 AI 대시보드가 아니라 **전문 악보 제작·편집 데스크탑 도구**로 보여야 합니다.

우선순위는 다음과 같습니다.

1. 악보가 항상 가장 먼저 보일 것
2. 장시간 편집에 피로하지 않을 것
3. note/chord/layout 같은 고밀도 control을 명확히 구분할 것
4. Windows/macOS 모두에서 자연스러울 것
5. 판매용 악보 제작 도구로서 출판·조판의 정밀함을 느끼게 할 것
6. 유행 스타일을 그대로 복제하지 않고 AudioScoreTool만의 정체성을 만들 것

제품 화면은 두 문맥으로 나눕니다.

- **Management** — 새 악보, 라이브러리, 작업 내역, benchmark, 설정
- **Studio** — 실제 악보 수정, 조판, 검증, 미리보기, export

---

## 2. 미학 후보 검토

뉴모피즘이나 미니멀리즘을 전제로 시작하지 않습니다. 다음 계열을 모두 검토하고 제품 적합성으로 판단합니다.

| 스타일 | 장점 | 리스크 | AudioScoreTool 적용 판단 |
| --- | --- | --- | --- |
| Swiss / International | 높은 정렬감, 정보 위계, 오래 봐도 안정적 | 지나치게 건조해질 수 있음 | **핵심 구조에 채택** |
| Editorial / Print-inspired | 악보·출판 제품과 직접 연결 | 문서 앱처럼 보일 수 있음 | **Management/조판에 채택** |
| Contemporary Pro Audio | 전문 음악 도구 인상, 고밀도 control에 강함 | dark chrome이 과하면 답답함 | **Studio에 채택** |
| Instrument / Industrial | 상태·경계가 명확하고 정밀함 | 엔지니어링 툴처럼 보일 수 있음 | **Studio panel logic에 제한 채택** |
| Bauhaus / Geometric Modernism | 브랜드 개성이 강하고 음악/그래픽과 잘 맞음 | 장식이 앞서면 score와 경쟁 | **브랜드 geometry와 small accent에 제한 채택** |
| Apple/HIG Refined Utility | 익숙하고 세련됨 | macOS 복제처럼 보일 위험 | spacing/modal discipline만 참고 |
| Fluent / Acrylic | layer 표현이 쉽고 Windows 친화적 | blur 남용 시 가독성 저하 | modal/backdrop 일부만 참고 |
| Neumorphism | pressed state의 물성 표현 | 낮은 대비, 고밀도 UI와 충돌 | **micro-control pressed state만 허용** |
| Glassmorphism | 현대적이고 시각적 깊이 표현 | editor 경계가 흐려짐 | backdrop 정도만 허용 |
| Skeuomorphism / Analog Studio | 음악 도구 정체성이 강함 | 쉽게 촌스럽고 무거워짐 | transport 물성 참고 외 비채택 |
| Neo-brutalism | 높은 개성, 즉각적 구분 | 악보 출판의 정교함과 충돌 | 비채택 |
| Soft/Scandinavian Minimal | 편안하고 친숙함 | 전문 편집기 밀도가 약해질 수 있음 | surface 온도감만 참고 |

### 평가 기준

후보는 다음 항목으로 판단합니다.

- 4시간 이상 작업 시 시각 피로도
- score paper가 chrome보다 먼저 보이는지
- 고밀도 inspector가 무너지지 않는지
- selected / hover / disabled / error / focus가 즉시 구별되는지
- 1366×768에서도 usable한지
- dark/light mode가 모두 자연스러운지
- Windows/macOS에서 특정 플랫폼 흉내처럼 보이지 않는지
- 브랜드 기억성이 있는지
- 몇 년 뒤에도 낡아 보이지 않을지

---

## 3. 최종 방향: Precision Editorial Workstation

최종안은 하나의 유행 스타일이 아니라 다음 세 축의 조합입니다.

### A. Precision Editorial — 정보 구조와 Management

Swiss/Editorial 계열에서 가져오는 요소:

- 강한 grid와 alignment
- spacing과 divider로 만드는 계층
- 불필요한 card nesting 제거
- 제목/본문/상태의 명확한 typography hierarchy
- 낮은 elevation
- warm-neutral paper 계열 surface

### B. Pro Audio / Notation Workstation — Studio

Logic/Ableton/Dorico 계열에서 가져오는 요소:

- 중앙 작업영역 우선
- Library / Score / Inspector의 명확한 역할 분리
- graphite chrome
- explicit panel divider
- compact command bar
- panel collapse / focus mode
- Page / Continuous view

### C. Restrained Geometric Modernism — Branding

Bauhaus/Geometric Modernism은 제품 전체 장식이 아니라 다음에만 사용합니다.

- app icon
- staff/waveform brand mark
- geometric spacing/alignment
- 제한된 상태 accent

즉, **악보 paper에는 브랜드 스타일을 덧씌우지 않습니다.**

---

## 4. 색상 의미 체계

브랜드 색과 편집 선택 색을 분리합니다.

```text
Paper             #fffef9  밝은 악보/출판 surface
Canvas            graphite
Management        warm neutral
Brand / Action    muted olive
Selection / Focus cobalt blue
Warning           muted amber
Danger            muted brick red
```

### Olive

- 제품 브랜드
- primary action
- readiness/positive accent

### Cobalt

- 현재 선택된 song/note/tab
- focus ring
- 편집 상태

이 구분으로 “브랜드 강조”와 “현재 편집 selection”을 시각적으로 혼동하지 않습니다.

강한 purple/neon gradient는 AI 제품의 전형적 인상을 만들기 때문에 주색으로 사용하지 않습니다.

---

## 5. Typography

장시간 데스크탑 사용을 기준으로 합니다.

```text
Body             13px 이상
Control          12px 이상
Caption          11px 이상
Eyebrow          9~10px (짧은 장식 정보만)
Section title    16~18px
Page title       21~27px
```

본문 정보를 9px 이하로 내리지 않습니다.

---

## 6. Management UI

Management 화면은 “AI SaaS card dashboard”처럼 보이지 않아야 합니다.

- card는 큰 의미 단위에만 사용
- 하위 정보는 divider/spacing으로 구분
- decorative blur/gradient를 기본 surface에 사용하지 않음
- hover elevation은 거의 느껴지지 않을 정도로 제한
- primary CTA만 olive action color 사용

---

## 7. Studio Workspace

시각 우선순위:

1. **Score paper**
2. Score command bar / revision / zoom / export
3. Inspector
4. Library
5. 전역 navigation

### Score canvas

- surrounding canvas는 graphite
- decorative grid 없음
- OS dark/light와 무관하게 score paper는 밝게 유지
- OSMD SVG geometry를 임의 stretch하지 않음
- page shadow는 paper와 canvas의 물리적 구분을 위한 최소 depth만 사용

### Library

- dashboard card가 아니라 Studio panel
- 선택 song은 cobalt 계열 selection state
- 제목을 1차 정보, source/artist/revision을 2차 정보로 표시

### Inspector

- note / chord / structure / layout / metadata 영역을 명확히 분리
- selected tab은 cobalt state
- panel 자체에는 강한 shadow나 glass 사용 금지

### View controls

- Library 표시/숨김
- Inspector 표시/숨김
- Page
- Continuous
- Focus

state는 localStorage에 보존하며 score model을 unmount하지 않습니다.

---

## 8. 뉴모피즘·Glass·Skeuomorphism 사용 규칙

이 스타일들을 금지하지는 않지만 **global theme로 사용하지 않습니다.**

### 허용

- pressed segmented control의 아주 약한 inset shadow
- modal backdrop의 제한된 blur
- transport/button에서 조작 상태를 설명하는 미세한 depth

### 금지

- 모든 card를 soft-shadow만으로 구분
- 모든 panel에 acrylic/glass 적용
- 실제 장비를 그대로 묘사한 knob/metal texture
- decorative gradient가 score보다 먼저 보이는 구성

시각 효과는 “스타일을 보여주기 위해서”가 아니라 상태 전달에 도움이 될 때만 사용합니다.

---

## 9. Preview와 PDF

Canonical state는 MusicXML입니다.

```text
Canonical Song / MusicXML
        ├─ OSMD SVG preview
        └─ Verovio + fpdf2 PDF export
```

UI 미학과 관계없이 조판 계약은 다음을 지킵니다.

- page size
- margins
- bars/system
- systems/page
- title block
- page/system breaks

Preview와 PDF는 가능한 한 동일한 canonical layout state를 반영해야 합니다.

---

## 10. Responsive / scaling

Release acceptance viewport:

- 1366×768
- 1440×900
- 1920×1080
- macOS Retina 13~14 inch
- Windows 100 / 125 / 150% scaling

규칙:

- 중앙 score width를 우선
- 좁아지면 Library/Inspector부터 축소/재배치
- 전역 horizontal overflow는 regression
- 긴 한국어 파일명, 긴 path/model 이름을 포함해 clipping 검증

---

## 11. Dark / Contrast / Motion

### Dark mode

- management chrome/panel은 dark surface
- score paper는 항상 밝게 유지
- selection cobalt는 dark surface에서도 명확해야 함

### Accessibility

- `focus-visible` 2px 이상
- 색만으로 상태 전달 금지
- `prefers-contrast: more` 존중
- forced-colors 대응
- 주요 control 30~38px 이상

### Motion

- 상태 설명용 100~180ms 이하
- spring/bounce 금지
- `prefers-reduced-motion: reduce`에서는 decorative motion 제거

---

## 12. Branding

앱 심볼은 단순 음표 glyph가 아니라 **audio waveform + staff movement를 추상화한 geometric mark**를 사용합니다.

브랜드 원칙:

- 단색에서도 인식 가능
- 16px tray/taskbar에서도 무너지지 않음
- 512px app icon에서도 과도하게 빈약하지 않음
- 악보 clef/note 자체를 그대로 로고로 쓰지 않음
- internal mark / native icon / README asset을 동일 언어로 통일

---

## 13. 자동 시각 계약

Playwright에서 다음을 회귀 테스트합니다.

- 지원 viewport에서 global horizontal overflow 없음
- body typography 13px 이상
- dark mode에서도 score paper 불변
- selection state와 brand action color가 구분됨
- pressed micro-control만 제한적 inset depth 사용
- reduced-motion에서 decorative transition 제거
- Studio view toggle의 상태 및 focus lifecycle 유지

---

## 14. v1.0 시각 완료 기준

다음이 모두 충족되어야 UI/UX polish를 완료로 봅니다.

- 모든 주요 화면이 동일 token system 사용
- management와 Studio의 시각 문법이 의도적으로 구분됨
- app icon과 내부 brand mark가 일치
- light/dark mode 모두 visual contract 통과
- 1366×768~1920×1080 overflow 없음
- Windows 125/150% scaling 실기기 검증
- modal clipping 없음
- 긴 한국어/경로 문자열 안정
- focus/keyboard 사용 가능
- score preview와 PDF page structure 비교 완료
- decorative effect가 score readability보다 우선하지 않음

UI 변경은 score/API/export semantics를 바꾸지 않습니다.
