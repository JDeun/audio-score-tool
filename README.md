# AudioScoreTool

> **음원 한 곡을 출판 가능한 악보로.**  
> 로컬 음원이나 YouTube 링크를 넣으면 다중 악기 채보, 자동 코드·가사 정렬, 앱 내 수정, 검증, 출판 조판, 최종 파일 생성까지 처리하는 로컬 우선 데스크탑 악보 제작 도구입니다.

**현재 버전: v0.8.0**

---

## 기본 원칙

AudioScoreTool은 처음부터 음표를 입력하는 악보 작성기가 아닙니다.

> **AI가 먼저 최대한 완성된 악보를 만들고, 사용자는 잘못된 부분과 출판 디테일만 수정합니다.**

```text
음원 파일 / YouTube URL
          ↓
정확도 우선 다중 악기 자동 채보
          ↓
보컬 · 피아노 · 기타 · 베이스 · 드럼 · 기타 감지 파트
          ↓
자동 코드 심벌 · 가사 인식/정렬
          ↓
SQLite 곡 라이브러리
          ↓
미리보기 · 세부 수정 · Revision · 출판 조판
          ↓
규칙 기반 QA + 선택적 LLM critic
          ↓
      [최종 파일 생성]
          ↓
PDF · MusicXML · MIDI · 파트보
```

---

## v0.8: DB 중심 프로젝트 관리

v0.8부터 **SQLite가 곡과 악보의 canonical state**입니다.

- 원본/현재 MusicXML 문서: SQLite
- Revision별 악보: SQLite
- 자동 코드/가사 alignment/검증 결과: SQLite JSON
- 출판 설정: SQLite
- OSMD/MuseScore가 요구하는 MusicXML 파일: 관리형 cache
- PDF/MIDI/MusicXML/파트보: 사용자가 `최종 파일 생성`을 실행했을 때만 export

채보가 끝났다는 이유만으로 PDF나 파트보를 미리 만들지 않습니다. 수정 중인 악보는 DB에서 관리하며, 악보를 수정하면 이전 Revision의 export는 자동 폐기됩니다.

기존 `jobs.sqlite3`는 최초 실행 시 `audio-score-tool.sqlite3`로 마이그레이션되고, 기존 파일 기반 Song/Publication 데이터도 순차적으로 DB로 이관됩니다.

자세한 내용: [`docs/STORAGE_V2.ko.md`](docs/STORAGE_V2.ko.md)

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

## 주요 기능

### 자동 생성

- 완성된 믹스 음원에서 다중 악기 자동 채보
- 보컬 / 피아노·키보드 / 기타 / 베이스 / 드럼 등 감지된 파트 생성
- 자동 코드 진행 추정 및 MusicXML `<harmony>` 삽입
- Demucs + WhisperX 기반 가사 인식/정렬
- 로컬 파일 / YouTube URL 입력
- 교체 가능한 transcription provider

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

로컬 Ollama/vLLM/LM Studio 등 OpenAI-compatible endpoint를 연결할 수 있고, 원격 endpoint는 HTTPS만 허용합니다. API key 자체는 저장하지 않고 환경변수 이름만 보존합니다. provider별 structured-output 확장에 의존하지 않고 JSON prompt + parser 방식으로 동작해 호환성을 넓혔습니다.

장기적으로는 현재 악보를 재합성한 audio와 원음을 정렬해 **audio-symbol mismatch를 먼저 검출한 뒤 LLM이 해당 근거를 설명**하도록 확장하는 것이 목표입니다.

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

### 4. MuseScore 4

MT3 계열 MIDI→MusicXML 변환과 최종 PDF/MIDI/파트보 생성에 사용합니다.

### 5. 데스크탑 앱

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
├─ assets/         # 관리형 MIDI 등 작은 binary asset
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
- AudioScore Native: project-owned checkpoint 목표

유료 배포 전에는 고정한 runtime/checkpoint revision과 실제 배포 artifact의 라이선스를 다시 검토해야 합니다.

자세한 내용: [`docs/THIRD_PARTY_LICENSES.ko.md`](docs/THIRD_PARTY_LICENSES.ko.md)

---

## 문서

- [저장 구조 v0.8](docs/STORAGE_V2.ko.md)
- [엔진 성능/선택](docs/ENGINE_PERFORMANCE.ko.md)
- [악보 검증](docs/VALIDATION.ko.md)
- [아키텍처](docs/ARCHITECTURE.ko.md)
- [악보 편집기](docs/EDITOR.ko.md)
- [벤치마크](docs/BENCHMARK.ko.md)
- [AudioScore Native](docs/NATIVE_MODEL.ko.md)
- [제3자 모델·라이선스](docs/THIRD_PARTY_LICENSES.ko.md)
