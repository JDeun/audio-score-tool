# 악보 편집기 설계

## 기본 원칙

AudioScoreTool 편집기는 SVG를 직접 수정하지 않습니다.

OpenSheetMusicDisplay(OSMD)는 MusicXML을 렌더링하는 미리보기 엔진이고, 모든 편집은 MusicXML 구조에 반영됩니다. v0.8부터는 **현재 MusicXML 문서가 SQLite 안에 저장되며 DB가 canonical state**입니다. 파일은 OSMD 미리보기 및 내장 music21/Verovio/fpdf2 같은 파일 경로가 필요한 처리에서만 관리형 cache로 materialize합니다.

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
내장 music21/Verovio/fpdf2 export
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

특히 Studio의 **첫 페이지 제목 영역 적용**은 곡 제목·아티스트·부제·작사/작곡/편곡·권리·글꼴 크기를 별도 두 번의 PATCH가 아니라 `PATCH /api/songs/{song_id}/credits` 한 번으로 저장합니다. API는 호출자가 확인한 `expected_revision`과 SQLite CAS를 검사하고, MusicXML/곡 메타데이터/출판 설정/Undo snapshot을 단일 트랜잭션에서 기록합니다. 실패하면 부분 저장 없이 롤백하고, 정상 저장은 단일 Undo로 복원해야 합니다.

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

MusicXML/MIDI/PDF/파트 PDF는 MuseScore 없이 처리합니다. MIDI 가져오기는 원본 tick을 보존하는 앱 내 변환기, MIDI 출력은 voice·악기 정보를 보존하도록 전처리한 music21, PDF/파트 PDF는 Verovio SVG → fpdf2 벡터 PDF 경로를 사용합니다. 상세 범위는 [MIDI/MusicXML 변환 계약](MIDI_MUSICXML_FIDELITY.ko.md)을 따릅니다.

### 선택 파트 합본과 인쇄

**최종 파일 생성 → 출력할 파트**에서 `전체 악보` 또는 `선택 파트 합본`을 고릅니다. 선택 합본은 원하는 파트를 한 악보에 묶은 MusicXML/PDF/MIDI이며, 파트별 출력도 함께 선택하면 해당 파트의 개별 MusicXML/PDF를 추가로 만듭니다. 이름이 같은 파트도 고유 ID로 구분하고 악보의 원래 파트 순서를 유지합니다.

선택 결과는 별도의 `곡 제목 - 선택 파트` 폴더에 `selected-score.musicxml`, `selected-score.pdf`, `selected-score.mid`로 저장합니다. 원본의 음표·크레딧·Revision은 변경하지 않으며 기존 전체 악보 출력도 보존합니다. 제외된 첫 파트에만 기록된 공통 템포는 선택 합본에 옮겨 재생 속도를 유지합니다. 악기별 조표·이조·음자리표는 다른 파트에서 복사하지 않습니다.

서버 계약은 `POST /api/songs/{song_id}/export-to`의 선택적 `part_ids` 및 `expected_revision`입니다. `part_ids`를 생략하면 기존 전체 출력과 같습니다. 빈 선택·중복·없는 파트는 거부하며, 화면에서 확인한 Revision 이후에 악보가 바뀌면 409 응답 후 현재 악보를 다시 확인해야 합니다. 선택 합본은 전체 악보의 Tier 2 출판 완료나 `time_to_publish_seconds` 완료로 집계하지 않습니다.

PDF를 포함해 저장하면 **생성한 PDF 열기 · 인쇄**가 표시됩니다. 이 버튼은 방금 생성한 정확한 출력본을 운영체제의 기본 PDF 뷰어로 엽니다. 페이지 범위·프린터·양면 인쇄는 뷰어의 인쇄 메뉴에서 선택합니다. 이후 악보가 수정되거나 같은 범위의 출력본이 교체되었다면 이전 버튼으로 다른 PDF를 열지 않고 다시 생성을 안내합니다. 실제 인쇄나 플랫폼별 PDF 뷰어 동작은 Windows/macOS 배포 인수시험에서도 확인해야 합니다.

### 완료 작업에서 편집 이어가기

현재 작업 카드의 **곡 라이브러리에서 편집**, 작업 내역의 **악보 편집**, OMR/직접 악보 가져오기의 **곡 라이브러리에서 검토**는 해당 `job_id`에 연결된 곡을 엽니다. 라이브러리 첫 번째 곡을 대신 선택하지 않습니다. 결과가 삭제되었거나 등록되지 않았다면 그 상태를 표시합니다.

채보 중 라이브러리로 이동하거나 같은 창을 새로고침해도 최근 작업 ID와 선택한 곡 ID를 복구합니다. 작업 상태는 브라우저 저장값을 그대로 믿지 않고 서버에서 다시 조회하며, 늦게 도착한 이전 요청이 새로 선택한 곡이나 작업을 덮어쓰지 않도록 검사합니다. 운영체제의 완료 알림은 아직 별도 후속 기능입니다.
