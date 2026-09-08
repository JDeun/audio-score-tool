# 악보 편집기 설계

## 기본 원칙

AudioScoreTool 편집기는 SVG를 직접 수정하지 않습니다.

OpenSheetMusicDisplay(OSMD)는 MusicXML을 렌더링하는 미리보기 엔진이고, 모든 편집은 MusicXML 구조에 반영됩니다. v0.8부터는 **현재 MusicXML 문서가 SQLite 안에 저장되며 DB가 canonical state**입니다. 파일은 OSMD/MuseScore 등 파일 경로가 필요한 처리에서만 관리형 cache로 materialize합니다.

```text
SQLite current_score_xml
  ↓
managed MusicXML cache
  ↓
Inspector edit
  ↓
validation + publication layout
  ↓
SQLite revision commit
  ↓
OSMD re-render
  ↓
[사용자가 최종 Export 요청]
  ↓
MuseScore export
```

따라서 미리보기와 최종 PDF는 동일한 DB Revision에서 파생됩니다.

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

사용자는 잘못 추정된 코드만 Inspector에서 보정합니다. 코드는 note onset에 anchor되므로 한 마디 안에서도 여러 번 변경할 수 있습니다.

## Revision / Undo

편집 전 현재 DB 상태를 `song_revisions`에 snapshot합니다.

Revision에는 다음이 포함됩니다.

- MusicXML 전체 문서
- note / rhythm / insert / delete
- measure structure / key / time
- lyric / chord
- tie / slur / beam / articulation
- title / artist
- publication settings

한 번의 사용자 저장을 하나의 Revision으로 처리하는 것을 원칙으로 합니다.

Undo는 해당 Revision의 MusicXML, 제목/아티스트, publication settings를 함께 되돌립니다. 새 편집이 commit되면 이전 Revision에서 생성된 export는 자동 무효화합니다.

## 출판 조판

MusicXML의 layout 정보를 이용해 다음을 반영하고 설정 원본은 SQLite `publication_settings`에 저장합니다.

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

화면 오버레이가 아니라 최종 MusicXML의 `credit`, `identification`, `rights`에도 기록합니다.

## Export 일관성

채보 완료 시점에는 PDF/MIDI/파트보를 만들지 않습니다. 사용자가 현재 Revision을 검수한 뒤 **최종 파일 생성**을 실행해야 persistent export가 생깁니다.

Export 창에서 다음을 선택합니다.

- MusicXML
- Full Score PDF
- MIDI
- 파트별 MusicXML + PDF
- OS 저장 폴더

동일한 곡 이름의 폴더가 이미 있으면 `(2)`, `(3)`처럼 충돌 없이 새 폴더를 만듭니다.

최종 Export 구조 예시:

```text
곡 제목/
├─ score.musicxml
├─ score.pdf
├─ score.mid
└─ parts/
   ├─ 01_voice.musicxml / 01_voice.pdf
   ├─ 02_piano.musicxml / 02_piano.pdf
   ├─ 03_guitar.musicxml / 03_guitar.pdf
   ├─ 04_bass.musicxml / 04_bass.pdf
   ├─ 05_drums.musicxml / 05_drums.pdf
   └─ ... 감지된 기타 파트
```

MusicXML만 내보내는 경우 MuseScore가 없어도 가능하며, PDF/MIDI/파트 PDF에는 MuseScore 4가 필요합니다.
