# 악보 편집기 설계

## 기본 원칙

AudioScoreTool 편집기는 SVG를 직접 수정하지 않습니다.

OpenSheetMusicDisplay(OSMD)는 MusicXML을 렌더링하는 미리보기 엔진이고, 모든 편집은 MusicXML 구조에 반영됩니다.

```text
MusicXML
  ↓
Inspector edit
  ↓
MusicXML revision
  ↓
OSMD re-render
  ↓
MuseScore export
```

미리보기와 최종 PDF가 서로 다른 데이터를 사용하는 문제를 방지하기 위해 현재 MusicXML을 단일 source of truth로 유지합니다.

## 편집 가능한 항목

### 음표

- A-G
- double-flat / flat / natural / sharp / double-sharp
- octave
- lyric

### 리듬

- whole
- half
- quarter
- eighth
- 16th
- 32nd
- 64th
- one/two dots

현재 MusicXML `divisions`에서 정확히 표현할 수 없는 리듬은 잘못된 XML을 만들지 않고 요청을 거부합니다.

### 음표와 쉼표

- note → rest
- rest → note
- before / after 삽입
- 삭제

### 표현기호

- staccato
- tenuto
- accent
- marcato
- tie start/stop
- slur start/stop
- beam begin/continue/end/hook

### 구조

- 마디 삽입/삭제
- key fifths -7 ~ +7
- major/minor
- time signature

다중 파트 악보에서 구조가 어긋나지 않도록 마디와 signature 변경은 모든 파트의 동일 위치에 적용합니다.

## 코드 심벌

자동 화성 분석이 생성한 코드는 MusicXML `<harmony>` 요소로 저장됩니다.

사용자는 잘못 추정된 코드만 Inspector에서 보정합니다.

코드는 note onset에 anchor되므로 한 마디 안에서 여러 번 변경할 수 있습니다.

## Revision / Undo

편집 전 현재 상태를 snapshot합니다.

Revision에는 다음이 포함됩니다.

- note / rhythm
- insert / delete
- measure structure
- key / time
- lyric
- chord
- tie / slur / beam / articulation
- title / credits
- publication settings

한 번의 사용자 저장을 하나의 Revision으로 처리하는 것을 원칙으로 합니다.

Undo는 MusicXML과 해당 시점의 publication settings를 함께 되돌립니다.

## 출판 조판

MusicXML의 layout 정보를 이용해 다음을 저장합니다.

- page size
- orientation
- page margins
- bars per system
- systems per page
- system distance
- title-space

### 첫 페이지 크레딧

- title
- subtitle/version
- composer
- lyricist
- arranger
- rights/source

화면 오버레이가 아니라 MusicXML `credit`, `identification`, `rights`에 기록합니다.

## Export 일관성

악보 Revision이 변경되면 이전 PDF / MIDI / part export를 현재 파일로 취급하지 않습니다.

사용자가 현재 Revision에서 다시 Export해야 다운로드 가능한 최신 파일이 생성됩니다.

최종 Export:

```text
Full Score
├─ MusicXML
├─ PDF
└─ MIDI

Parts
├─ Voice.musicxml / Voice.pdf
├─ Piano.musicxml / Piano.pdf
├─ Guitar.musicxml / Guitar.pdf
├─ Bass.musicxml / Bass.pdf
├─ Drums.musicxml / Drums.pdf
└─ ...
```
