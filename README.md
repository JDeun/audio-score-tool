# AudioScoreTool

> **음원 한 곡을 출판 가능한 악보로.**  
> 로컬 음원이나 YouTube 링크를 넣으면 다중 악기 채보, 자동 코드·가사 정렬, 앱 내 수정, 출판 조판, 최종 파일 생성까지 처리하는 로컬 우선 데스크탑 악보 제작 도구입니다.

**현재 버전: v0.8.0**

---

## 기본 원칙

AudioScoreTool은 처음부터 음표를 입력하는 악보 작성기가 아닙니다.

> **AI가 먼저 최대한 완성된 악보를 만들고, 사용자는 잘못된 부분과 출판 디테일만 수정합니다.**

```text
음원 파일 / YouTube URL
          ↓
다중 악기 자동 채보
          ↓
보컬 · 피아노 · 기타 · 베이스 · 드럼 · 기타 감지 파트
          ↓
자동 코드 심벌 · 가사 인식/정렬
          ↓
SQLite 곡 라이브러리
          ↓
미리보기 · 세부 수정 · Revision · 출판 조판
          ↓
      [최종 파일 생성]
          ↓
PDF · MusicXML · MIDI · 파트보
```

---

## v0.8의 핵심 변경: DB 중심 프로젝트 관리

v0.8부터 **SQLite가 곡과 악보의 canonical state**입니다.

- 원본/현재 MusicXML 문서: SQLite
- Revision별 악보: SQLite
- 자동 코드/가사 alignment: SQLite JSON
- 출판 설정: SQLite
- OSMD/MuseScore가 요구하는 MusicXML 파일: 관리형 cache
- PDF/MIDI/MusicXML/파트보: 사용자가 `최종 파일 생성`을 실행했을 때만 export

따라서 채보가 끝났다는 이유만으로 PDF나 파트보를 미리 만들지 않습니다. 수정 중인 악보는 DB에서 관리하며, 악보를 수정하면 이전 Revision의 export는 자동 폐기됩니다.

기존 `jobs.sqlite3`는 최초 실행 시 `audio-score-tool.sqlite3`로 마이그레이션되고, 기존 파일 기반 Song/Publication 데이터도 순차적으로 DB로 이관됩니다.

자세한 내용: [`docs/STORAGE_V2.ko.md`](docs/STORAGE_V2.ko.md)

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

API에서는 필요한 포맷만 선택할 수도 있습니다.

```json
{
  "formats": ["musicxml", "pdf", "midi", "parts"]
}
```

---

## 채보 엔진

| 엔진 | 용도 | 장점 | 주의점 |
|---|---|---|---|
| **MR-MT3 via MT3-Infer** | **기본값** | 빠른 추론, instrument leakage 완화, permissive 배포 경로 | YourMT3+보다 절대 정확도는 낮을 수 있음 |
| **YourMT3+ via MT3-Infer** | 품질 비교 | Slakh2100 계열에서 높은 multi-instrument 성능 | 더 무겁고 상용 배포 전 provenance 재검토 권장 |
| **MuScriptor** | 연구/품질 비교 | 최신 대형 모델의 높은 실제 혼합음원 성능 | 공개 weights가 CC-BY-NC이므로 상용 기본값 불가 |
| **AudioScore Native** | 장기 R&D | 프로젝트가 checkpoint를 완전히 소유 가능 | 현재는 학습된 고품질 checkpoint가 필요 |

기본값:

```text
provider = mt3_infer
model    = mr_mt3
```

모델 선택 기준과 공개 benchmark 해석은 [`docs/ENGINE_PERFORMANCE.ko.md`](docs/ENGINE_PERFORMANCE.ko.md)를 참고하세요.

---

## 빠른 시작

### 1. 프로젝트 설치

```bash
git clone https://github.com/JDeun/audio-score-tool.git
cd audio-score-tool
uv sync --extra dev
```

MT3-Infer를 프로젝트 환경에 직접 설치하려면:

```bash
uv sync --extra mt3
```

`uvx`가 있으면 고정된 `mt3-infer[torch]==0.2.0` runtime을 사용할 수도 있습니다.

### 2. MuseScore 4

MR-MT3/YourMT3가 만든 MIDI를 MusicXML로 변환하고 최종 PDF/MIDI/파트보를 생성하는 데 사용합니다.

앱이 자동으로 찾지 못하면 설정에서 실행 파일 경로를 지정합니다.

### 3. 데스크탑 앱

```bash
cd desktop
npm install
npm run desktop:dev
```

---

## 엔진 설정

### MR-MT3 — 기본 권장

```bash
export AST_TRANSCRIPTION_ENGINE=mt3_infer
export AST_MT3_MODEL=mr_mt3
```

### YourMT3+ — 품질 비교

```bash
export AST_TRANSCRIPTION_ENGINE=mt3_infer
export AST_MT3_MODEL=yourmt3
```

### MuScriptor — 비상업 연구/비교

```bash
export AST_TRANSCRIPTION_ENGINE=muscriptor
uvx hf auth login
```

### AudioScore Native — 자체 checkpoint

```bash
uv sync --extra native
export AST_TRANSCRIPTION_ENGINE=native
export AST_NATIVE_CHECKPOINT=/path/to/audio-score-native.pt
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

## 성능 비교

앱의 Benchmark 기능은 모델 간 다음 항목을 비교할 수 있습니다.

- 처리 시간
- 성공 여부
- 가사 attachment ratio
- Ground Truth MIDI가 있을 때 Note Precision / Recall / F1 / Onset MAE

제품 의사결정에는 공개 논문의 서로 다른 dataset 숫자를 직접 비교하기보다 **동일한 실제 곡 세트에서 MR-MT3와 YourMT3+를 A/B 테스트**하는 것을 권장합니다.

---

## 라이선스

- MT3-Infer: MIT
- MR-MT3 원 구현/공개 checkpoint: MIT 표기
- YourMT3 계열: 배포 provenance를 릴리스 전 재검토
- MuScriptor 코드: MIT, 공개 weights: CC-BY-NC
- AudioScore Native: project-owned checkpoint 목표

유료 배포 전에는 고정한 runtime/checkpoint revision과 실제 배포 artifact의 라이선스를 다시 검토해야 합니다.

자세한 내용: [`docs/THIRD_PARTY_LICENSES.ko.md`](docs/THIRD_PARTY_LICENSES.ko.md)

---

## 문서

- [저장 구조 v0.8](docs/STORAGE_V2.ko.md)
- [엔진 성능/선택](docs/ENGINE_PERFORMANCE.ko.md)
- [아키텍처](docs/ARCHITECTURE.ko.md)
- [악보 편집기](docs/EDITOR.ko.md)
- [벤치마크](docs/BENCHMARK.ko.md)
- [AudioScore Native](docs/NATIVE_MODEL.ko.md)
- [제3자 모델·라이선스](docs/THIRD_PARTY_LICENSES.ko.md)
