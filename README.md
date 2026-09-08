# AudioScoreTool

> **음원이나 기존 악보를 출판 가능한 편집 악보로.**  
> 로컬 음원·YouTube·PDF/이미지 악보를 MusicXML 중심 프로젝트로 통합하고, 자동 채보/OMR, 코드·가사, 검증, 편집, 출판 조판, 최종 파일 생성을 처리하는 로컬 우선 데스크탑 악보 제작 도구입니다.

**현재 버전: v0.8.0**

---

## 기본 원칙

AudioScoreTool은 처음부터 모든 음표를 직접 입력하게 하는 악보 작성기가 아닙니다.

> **AI/OMR이 먼저 최대한 완성된 악보를 만들고, 사용자는 잘못된 부분과 출판 디테일만 수정합니다.**

```text
음원 파일 / YouTube URL ─→ AMT ─┐
PDF / 이미지 악보 ───────→ OMR ─┼→ Canonical MusicXML
MusicXML / MIDI ────────────────┘
                                  ↓
                         SQLite 곡 라이브러리
                                  ↓
                  미리보기 · 검증 · 편집 · Revision
                                  ↓
                         출판 조판 · 최종 Export
```

---

## v0.8: DB 중심 프로젝트 관리

v0.8부터 **SQLite가 곡과 악보의 canonical state**입니다.

- 원본/현재 MusicXML 문서: SQLite
- Revision별 악보: SQLite
- 자동 코드/가사 alignment/검증 결과: SQLite JSON
- 출판 설정: SQLite
- OSMD/외부 도구가 요구하는 MusicXML 파일: 관리형 cache
- OMR 원본 PDF/이미지: managed asset
- PDF/MIDI/MusicXML/파트보: 사용자가 `최종 파일 생성`을 실행했을 때만 export

채보가 끝났다는 이유만으로 PDF나 파트보를 미리 만들지 않습니다. 수정 중인 악보는 DB에서 관리하며, 악보를 수정하면 이전 Revision의 export는 자동 폐기됩니다.

기존 `jobs.sqlite3`는 최초 실행 시 `audio-score-tool.sqlite3`로 마이그레이션되고, 기존 파일 기반 Song/Publication 데이터도 순차적으로 DB로 이관됩니다.

자세한 내용: [`docs/STORAGE_V2.ko.md`](docs/STORAGE_V2.ko.md)

---

## 입력 방식

### 1. 음원 / YouTube → 자동 채보

완성된 믹스 음원을 다중 악기 채보 모델로 처리합니다.

### 2. PDF / 이미지 악보 → OMR

Audiveris를 외부 OMR backend로 사용해 PDF/PNG/JPG/TIFF/BMP 악보를 MusicXML로 변환합니다.

```text
PDF / Scan
   ↓
Audiveris OMR
   ↓
Normalized MusicXML
   ↓
기존 DB / 검증 / 편집 / 조판 파이프라인
```

원본 PDF/이미지는 나중에 OMR 결과와 대조 검증할 수 있도록 곡별 managed asset으로 보존합니다. OMR 결과는 자동으로 정답으로 간주하지 않으며, 기존 결정론적 validator와 선택적 LLM critic으로 검토합니다.

자세한 내용: [`docs/OMR.ko.md`](docs/OMR.ko.md)

---

## 품질 우선 채보 정책

속도보다 **최종 악보까지 필요한 사람의 수정량**을 줄이는 것을 우선합니다.

### 개인 / 비상업

```text
1. MuScriptor large    ← 기본값, 품질 최우선
2. YourMT3+            ← fallback
3. MR-MT3              ← 빠른 fallback
```

MuScriptor code는 MIT지만 공개 weights는 **CC BY-NC 4.0**입니다. 따라서 개인/비상업 모드에서만 허용합니다.

### 상용

```text
1. YourMT3+ via MT3-Infer  ← 정확도 우선 후보
2. MR-MT3                  ← MIT provenance가 더 단순한 fallback
```

YourMT3+ checkpoint와 `mt3-infer` vendored implementation은 Apache-2.0으로 표기되지만 공식 GitHub 저장소는 GPL-3.0으로 표시되므로 상용 배포 전 고정 revision 기준 provenance 검토가 필요합니다.

`auto` preset은 v0.8부터 **Quality**로 해석합니다. 제한된 하드웨어에서 속도를 우선해야 할 때만 Fast/Balanced를 명시적으로 선택합니다.

모델 비교와 근거: [`docs/ENGINE_PERFORMANCE.ko.md`](docs/ENGINE_PERFORMANCE.ko.md)

---

## MuseScore 비의존 정책

AudioScoreTool은 **MuseScore 4를 설치하지 않아도 전체 핵심 워크플로가 동작하도록 설계합니다.** MuseScore CLI를 runtime fallback으로 호출하지 않습니다.

```text
미리보기            OSMD
MIDI ↔ MusicXML     music21 (BSD)
파트 분리           AudioScoreTool 자체 MusicXML 처리
MusicXML → PDF       LilyPond + musicxml2ly
OMR                 Audiveris
```

- MusicXML 미리보기/편집 및 export는 MuseScore와 무관합니다.
- MIDI 변환은 `music21`이 담당합니다.
- PDF/파트 PDF가 필요할 때만 LilyPond와 `musicxml2ly`가 필요합니다.
- PDF renderer가 없어도 채보·편집·MusicXML/MIDI 작업은 계속 사용할 수 있습니다.

`musicxml2ly`가 MusicXML의 모든 표기 기능을 완벽하게 보존하는 것은 아니므로 실제 타깃 악보 Golden Set에서 PDF fidelity는 별도로 검증합니다.

---

## 주요 기능

### 자동 생성

- 완성된 믹스 음원에서 다중 악기 자동 채보
- 보컬 / 피아노·키보드 / 기타 / 베이스 / 드럼 등 감지된 파트 생성
- 자동 코드 진행 추정 및 MusicXML `<harmony>` 삽입
- Demucs + WhisperX 기반 가사 인식/정렬
- 로컬 파일 / YouTube URL 입력
- PDF/이미지 악보 OMR 가져오기
- 교체 가능한 transcription / notation backend

### 앱 내 악보 편집

- MusicXML 기반 OSMD 실시간 미리보기
- 음정 / 옥타브 / 샵·플랫
- 온음표 ~ 64분음표 / 점음표
- 음표 ↔ 쉼표
- 음표·쉼표 삽입 / 삭제
- 마디 삽입 / 삭제
- 조표 / 장·단조 / 박자표
- 가사 / 코드 심벌
- Tie / Slur / Beam
- Staccato / Tenuto / Accent / Marcato
- DB 기반 Revision / Undo / 원본 복원

### 악보 검증

검증은 LLM 단독 판정이 아니라 다음 두 단계입니다.

1. **결정론적 검사**: 마디 duration, 일반 음역 이탈, 쉼표 lyric, 비정상 tie, 빈 part 등
2. **선택적 LLM critic**: 음악적 문맥에서 의심 구간을 우선순위화하고 검토 이유를 설명

LLM은 원음을 직접 측정하는 acoustic verifier가 아니므로 `LLM 가설`로 표시하며 **악보를 자동 수정하지 않습니다.** 결과는 DB의 `song_analysis.validation_report`에 저장됩니다.

OMR 입력의 경우 원본 PDF/이미지를 보존하므로 향후 원본 악보 이미지 ↔ 인식 MusicXML 렌더링의 멀티모달 차이 검증을 추가할 수 있습니다.

자세한 내용: [`docs/VALIDATION.ko.md`](docs/VALIDATION.ko.md)

### 출판 조판

- A4 / Letter, 세로 / 가로
- 한 줄당 마디 수
- 페이지당 시스템 수
- 시스템 간격
- 페이지 여백
- 첫 페이지 제목 영역
- 제목 / 부제 / 작곡 / 작사 / 편곡 / 저작권·출처

### 최종 Export

`최종 파일 생성` 전에는 PDF/파트보를 만들지 않습니다.

지원 포맷:

- Full Score MusicXML
- Full Score PDF
- MIDI
- 감지된 각 악기별 MusicXML / PDF

Tauri native folder picker에서 실제 저장 위치를 선택합니다. 같은 이름의 폴더가 이미 있으면 `(2)`, `(3)`처럼 충돌 없이 생성합니다.

---

## 빠른 시작

### 1. 프로젝트 설치

```bash
git clone https://github.com/JDeun/audio-score-tool.git
cd audio-score-tool
uv sync --extra dev
```

`music21`은 기본 dependency에 포함되어 MIDI↔MusicXML 변환을 담당합니다.

### 2. 개인/비상업 품질 최우선 — MuScriptor

먼저 Hugging Face에서 MuScriptor model license를 수락하고 로그인합니다.

```bash
uvx hf auth login
export AST_USAGE_MODE=personal
```

기본 정책이 `personal → muscriptor → large`이므로 별도 provider 설정 없이 사용 가능합니다.

### 3. 상용 모드

```bash
export AST_USAGE_MODE=commercial
```

MuScriptor는 자동 차단되고 MT3-Infer + YourMT3+가 품질 우선 후보가 됩니다. MR-MT3로 고정하려면:

```bash
export AST_TRANSCRIPTION_ENGINE=mt3_infer
export AST_MT3_MODEL=mr_mt3
```

### 4. PDF export — LilyPond 권장

현재 production stable은 LilyPond 2.26 계열입니다. `lilypond`와 `musicxml2ly`가 PATH에 있으면 자동 인식합니다.

```bash
export AST_LILYPOND_CMD=lilypond
export AST_MUSICXML2LY_CMD=musicxml2ly
```

### 5. PDF/이미지 OMR — Audiveris

Audiveris를 설치하고 CLI 경로를 지정합니다.

```bash
export AST_AUDIVERIS_CMD=audiveris
```

### 6. 데스크탑 앱

```bash
cd desktop
npm install
npm run desktop:dev
```

---

## 데이터 구조

```text
SQLite: audio-score-tool.sqlite3
├─ jobs
├─ songs
├─ song_revisions
├─ song_analysis
└─ publication_settings

Application Data/
├─ cache/          # 재생성 가능한 working materialization
├─ assets/         # MIDI, OMR 원본 등 곡별 managed asset
├─ jobs/           # 실행 중/히스토리용 job workspace
└─ exports/        # 명시적 최종 파일 생성 결과만 존재
```

대용량 원본 audio, Demucs stem, 모델 checkpoint는 SQLite BLOB으로 넣지 않습니다.

---

## 제품용 성능 평가

공개 leaderboard의 숫자만으로 최종 엔진을 고르지 않습니다. 실제 타깃 곡 Golden Set에서 다음을 함께 측정하는 것이 핵심입니다.

- note onset/offset F1
- instrument assignment F1
- drum/bass/melody F1
- chord/lyrics accuracy
- OMR measure/note/accidental/tie error rate
- 사람이 수정한 note/chord 수 / 음악 1분
- 최종 악보까지의 실제 편집 시간
- real-time factor / peak VRAM
- 검증기가 실제 오류를 얼마나 잘 우선순위화했는지

**최종 편집 시간이 가장 중요한 제품 KPI**입니다.

---

## 라이선스

- MuScriptor code: MIT / 공개 weights: CC BY-NC 4.0 → 개인·비상업만
- MT3-Infer: MIT
- YourMT3+ checkpoint: Apache-2.0 표기 / 공식 source repo GPL-3.0 → 상용 배포 전 provenance 검토
- MR-MT3 원 구현/공개 checkpoint: MIT 표기
- music21: BSD 3-Clause
- LilyPond: GPL → 외부 실행 프로그램으로 사용
- Audiveris: GNU AGPL v3 → 외부 OMR 프로그램으로 사용, 번들/수정 시 별도 의무 검토
- AudioScore Native: project-owned checkpoint 목표

유료 배포 전에는 고정한 runtime/checkpoint/external-tool revision과 실제 배포 artifact의 라이선스를 다시 검토해야 합니다.

자세한 내용: [`docs/THIRD_PARTY_LICENSES.ko.md`](docs/THIRD_PARTY_LICENSES.ko.md)

---

## 문서

- [저장 구조 v0.8](docs/STORAGE_V2.ko.md)
- [엔진 성능/선택](docs/ENGINE_PERFORMANCE.ko.md)
- [PDF/이미지 OMR](docs/OMR.ko.md)
- [악보 검증](docs/VALIDATION.ko.md)
- [아키텍처](docs/ARCHITECTURE.ko.md)
- [악보 편집기](docs/EDITOR.ko.md)
- [벤치마크](docs/BENCHMARK.ko.md)
- [AudioScore Native](docs/NATIVE_MODEL.ko.md)
- [제3자 모델·라이선스](docs/THIRD_PARTY_LICENSES.ko.md)
