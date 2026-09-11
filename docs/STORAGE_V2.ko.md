# AudioScoreTool v0.8 저장 구조

## 목표

v0.8부터 **SQLite가 악보 프로젝트의 단일 기준 상태(source of truth)** 입니다. MusicXML 파일은 더 이상 앱 내부의 영구 편집 상태가 아니라, renderer/component가 파일 경로를 요구할 때만 생성되는 관리형 캐시 또는 사용자가 요청한 최종 Export입니다.

```text
Audio / YouTube
      ↓
Transcription Job
      ↓
MIDI + MusicXML (managed job cache)
      ↓
SQLite
├─ songs.current_score_xml
├─ songs.original_score_xml
├─ song_revisions
├─ song_analysis
└─ publication_settings
      ↓
앱 내 미리보기 / 편집 / Undo
      ↓
[최종 파일 생성]
      ↓
MusicXML / PDF / MIDI / Parts
```

## 저장 계층

### SQLite

- 곡 메타데이터
- 원본/현재 MusicXML 문서
- Revision별 MusicXML
- Revision별 제목/아티스트/출판 설정
- 자동 코드 분석 JSON
- 가사 transcript/alignment JSON
- 출판 레이아웃 설정
- 기존 Job history

### Managed cache

renderer/library/component가 파일 경로를 요구할 때만 DB의 MusicXML을 임시 materialize합니다.

- `cache/scores/<song_id>/score.musicxml`
- `cache/export/<temporary-id>/...`
- Job 실행 중의 모델 intermediate

이 경로는 언제든 재생성할 수 있으므로 canonical state가 아닙니다.

### Managed assets

MIDI처럼 다시 분석하거나 기준 자료로 사용할 수 있는 작은 binary artifact는 `assets/songs/<song_id>/`에 보관하고 DB가 위치를 관리합니다. 원본 WAV/MP3, Demucs stem, 모델 checkpoint 같은 대용량 파일을 SQLite BLOB으로 넣지 않습니다.

### Explicit exports

`exports/<song_id>/`는 사용자가 **최종 파일 생성**을 실행했을 때만 만들어집니다.

- `score.musicxml`
- `score.pdf`
- `score.mid`
- `parts/*.musicxml`
- `parts/*.pdf`

악보를 수정하면 해당 Revision에서 만든 export는 자동 폐기됩니다.

## 마이그레이션

기존 `jobs.sqlite3`는 첫 실행 시 `audio-score-tool.sqlite3`로 복사됩니다. 기존 `songs.original_musicxml/current_musicxml`이 가리키던 파일은 한 번 읽어 `original_score_xml/current_score_xml`로 이관합니다. 기존 `publication.json`도 최초 조회 시 SQLite로 lazy migration합니다.

## Export API

`POST /api/songs/{song_id}/export`

기본값은 전체 포맷입니다. 필요한 포맷만 생성할 수도 있습니다.

```json
{
  "formats": ["musicxml", "pdf", "midi", "parts"]
}
```

현재 notation/export 경로는 외부 MuseScore/LilyPond 설치를 요구하지 않습니다.

- MusicXML preview: OpenSheetMusicDisplay
- MIDI ↔ MusicXML: embedded `music21`
- PDF/파트 PDF: MusicXML → embedded Verovio SVG → `fpdf2` vector PDF
- 파트 분리: 자체 MusicXML 처리

따라서 MusicXML/MIDI/PDF/part export는 packaged sidecar와 앱에 포함된 notation stack으로 처리합니다. 선택적 AMT/YouTube/OMR component의 실제 배포 상태는 `DEPENDENCIES.ko.md`와 release gate를 따릅니다.
