# AudioScoreTool

> **음원 한 곡을 출판 가능한 악보로.**  
> 로컬 음원이나 YouTube 링크를 넣으면 보컬·피아노·기타·베이스·드럼 등 감지된 파트를 자동으로 채보하고, 코드와 가사를 정렬한 뒤 앱에서 수정·조판해 PDF / MusicXML / MIDI로 내보내는 로컬 우선 데스크탑 앱입니다.

**현재 버전: v0.6.0**

---

## 한눈에 보기

```text
음원 파일 / YouTube URL
          ↓
      자동 채보
          ↓
┌─────────────────────────────┐
│ 보컬 · 피아노 · 기타 · 베이스 · 드럼 │
│ 코드 심벌 · 가사 · Full Score       │
└─────────────────────────────┘
          ↓
      곡 라이브러리
          ↓
  악보 미리보기 · 세부 수정
          ↓
   출판 레이아웃 · 제목/크레딧
          ↓
 PDF · MusicXML · MIDI · 파트보
```

AudioScoreTool의 기본 철학은 **사용자가 처음부터 악보를 입력하는 것이 아니라, AI가 먼저 최대한 완성된 악보를 만들고 사람은 틀린 부분과 출판 디테일만 수정하는 것**입니다.

---

## 주요 기능

### 자동 채보

- 완성된 믹스 음원에서 다중 악기 자동 채보
- 보컬 / 피아노·키보드 / 기타 / 베이스 / 드럼 등 감지된 파트 생성
- Full Score와 악기별 파트보 생성
- 자동 코드 진행 추정 및 마디 위 코드 심벌 표기
- Demucs + WhisperX 기반 보컬 가사 인식·정렬
- 로컬 파일과 YouTube URL 입력 지원

### 악보 편집

- MusicXML 기반 실시간 악보 미리보기
- 음정 / 옥타브 / 샵·플랫 수정
- 온음표 ~ 64분음표, 점음표 리듬 수정
- 음표 ↔ 쉼표 변환
- 음표·쉼표 삽입 / 삭제
- 마디 삽입 / 삭제
- 조표 / 장·단조 / 박자표 수정
- 가사 수정
- 코드 심벌 수정
- Tie / Slur / Beam
- Staccato / Tenuto / Accent / Marcato
- Revision / Undo / 원본 복원

### 출판용 조판

- A4 / Letter
- 세로 / 가로
- 한 줄당 마디 수
- 한 페이지당 시스템 수
- 시스템 간격
- 상·하·좌·우 여백
- 첫 페이지 제목 영역
- 제목 / 부제
- 작곡 / 작사 / 편곡
- 저작권·출처
- Full Score 및 파트별 PDF / MusicXML

### 데스크탑 제품 기능

- `새 악보 / 곡 라이브러리 / 작업 내역 / 성능 비교 / 설정` 단일 내비게이션
- 첫 실행 온보딩
- CUDA / Apple Metal / CPU 자동 감지
- Auto / Fast / Balanced / Quality 프리셋
- 작업 큐 및 동시 GPU 작업 방지
- 실행 중 전체 프로세스 트리 취소
- SQLite 기반 작업 히스토리
- 실패 작업 재실행
- 출력 폴더 열기
- 저장공간 정리
- Hugging Face 인증 상태 확인
- 로컬 실행 파일 경로 설정
- Windows / macOS / Linux 데스크탑 패키징

---

# 빠른 시작

## 1. 저장소 준비

```bash
git clone https://github.com/JDeun/audio-score-tool.git
cd audio-score-tool
uv sync --extra dev
```

## 2. MuScriptor 모델 사용 권한 승인

현재 공개 MuScriptor 모델 weights는 Hugging Face에서 라이선스 승인이 필요한 gated model입니다.

1. Hugging Face의 MuScriptor 모델 페이지에서 라이선스 수락
2. 로컬 로그인

```bash
uvx hf auth login
```

AudioScoreTool은 토큰 값을 UI에 표시하거나 자체 저장하지 않습니다.

## 3. MuseScore 4 설치

최종 PDF / MIDI 렌더링에는 MuseScore 4 이상이 필요합니다.

앱이 자동으로 찾지 못하면 **설정 → 도구 경로**에서 실행 파일을 지정할 수 있습니다.

## 4. 데스크탑 앱 실행

```bash
cd desktop
npm install
npm run desktop:dev
```

첫 실행 시 온보딩에서 백엔드, 모델 도구, Hugging Face 인증 상태를 확인할 수 있습니다.

---

# 사용 흐름

## 새 악보

### 로컬 음원

1. WAV / MP3 / FLAC / M4A 등의 파일을 드래그 앤 드롭
2. 품질 프리셋 선택
3. 가사 언어 및 가사 정렬 여부 선택
4. **자동 채보 시작**
5. 완료 후 **곡 라이브러리에서 편집**

### YouTube

1. `새 악보 → YouTube 링크`
2. URL 입력
3. 제목·채널·재생시간 확인
4. 콘텐츠 처리 권한 확인
5. 자동 채보 시작

한 번에 한 곡을 관리하는 제품 흐름을 유지하기 위해 재생목록 일괄 처리는 지원하지 않습니다.

YouTube 콘텐츠는 사용자가 다운로드·처리 권한을 가지고 있거나 YouTube/권리자가 허용한 콘텐츠에만 사용해야 합니다.

---

# 자동 생성 결과

실제 감지된 파트를 기준으로 다음과 같은 구조가 만들어집니다.

```text
곡 이름/
├─ Full Score
│  ├─ score.musicxml
│  ├─ score.pdf
│  └─ score.mid
│
└─ Parts
   ├─ Voice.musicxml / Voice.pdf
   ├─ Piano.musicxml / Piano.pdf
   ├─ Guitar.musicxml / Guitar.pdf
   ├─ Bass.musicxml / Bass.pdf
   ├─ Drums.musicxml / Drums.pdf
   └─ ... 감지된 기타 파트
```

음원에 없는 악기를 임의로 추가하지 않습니다.

---

# 자동 코드 심벌

MuScriptor가 추출한 pitched part의 음들을 시간축으로 종합해 화성을 추정하고 MusicXML `<harmony>`로 기록합니다.

예:

```text
| C        Am7      | F        G/B      |
| C/E      F        | Dm7      G7       |
```

대표 지원 코드:

- Major / Minor
- 6 / m6
- 7 / maj7 / m7
- 9 / maj9 / m9
- sus2 / sus4
- dim / dim7
- aug
- m7b5
- slash chord

자동 화성 분석은 사람이 판정한 코드와 항상 같다고 보장하지 않습니다. **코드 편집기는 자동 생성 결과를 보정하기 위한 기능**입니다.

---

# 곡 라이브러리와 편집기

완료된 채보는 `Job`이 아니라 별도의 `Song`으로 관리됩니다.

```text
Song
├─ 원본 MusicXML
├─ 현재 MusicXML
├─ 자동 코드
├─ 감지된 악기 파트
├─ 가사
├─ 출판 설정
├─ Revision
└─ Export
```

OpenSheetMusicDisplay(OSMD)가 현재 MusicXML을 앱 안에서 SVG 악보로 렌더링합니다.

미리보기와 Export가 서로 다른 데이터를 사용하지 않도록 **MusicXML을 단일 source of truth**로 유지합니다.

악보 수정 후에는 이전 PDF/MIDI/파트보를 자동으로 구버전 처리하고, 현재 Revision에서 다시 Export해야 합니다.

---

# 성능 비교

현재 컴퓨터에서 모델 조합을 직접 비교할 수 있습니다.

비교 대상:

- MuScriptor small / medium / large
- WhisperX 조합
- 처리 시간
- 성공 여부
- 가사 attachment ratio

Ground Truth MIDI를 제공하면 다음 지표도 계산합니다.

- Note Precision
- Note Recall
- Note F1
- Onset MAE

CLI에서도 실행할 수 있습니다.

```bash
uv run audio-score benchmark song.wav \
  --language ko \
  --profile all \
  --reference-midi reference.mid
```

---

# 하드웨어 정책

| 환경 | MuScriptor | Demucs | WhisperX |
|---|---|---|---|
| NVIDIA GPU | CUDA | CUDA | CUDA / FP16 |
| Apple Silicon | MPS | CPU | CPU / INT8 |
| CPU only | CPU | CPU | CPU / INT8 |

기본 Auto 프리셋:

- CPU only → `Fast`
- Apple Silicon → `Balanced`
- NVIDIA CUDA → `Balanced`

실제 최적 조합은 **성능 비교** 화면에서 대표 음원으로 측정하는 것을 권장합니다.

---

# 데스크탑 빌드

```bash
uv sync --extra desktop
cd desktop
npm install
npm run desktop:build
```

빌드 과정:

1. 플랫폼별 앱 아이콘 생성
2. PyInstaller로 Python/FastAPI sidecar 생성
3. Tauri 데스크탑 번들 생성

GitHub Actions는 다음 플랫폼의 unsigned bundle을 실제로 빌드합니다.

- Windows
- macOS
- Linux

공개 배포용 코드서명/공증은 저장소에 자격증명을 포함하지 않습니다.

---

# 개발용 CLI / API

환경 진단:

```bash
uv run audio-score doctor
```

파일 채보:

```bash
uv run audio-score run song.mp3 --language ko --output outputs
```

로컬 API:

```bash
uv run audio-score-api
```

기본 주소:

```text
http://127.0.0.1:8080
```

---

# 로컬 데이터 위치

- macOS: `~/Library/Application Support/AudioScoreTool`
- Windows: `%LOCALAPPDATA%\AudioScoreTool`
- Linux: `$XDG_DATA_HOME/audio-score-tool` 또는 `~/.local/share/audio-score-tool`

저장 항목:

- SQLite 작업 기록
- 입력 음원 및 retry용 원본
- stems
- MusicXML / PDF / MIDI
- 곡 Revision
- 출판 설정
- 벤치마크 결과
- 도구 실행 경로 설정

---

# 라이선스 주의

AudioScoreTool 코드와 외부 모델 가중치의 라이선스는 별개입니다.

현재 공개 **MuScriptor model weights는 CC BY-NC 4.0**입니다. 따라서 현재 weights를 그대로 상업 서비스나 유료 제품에 재배포하려면 upstream의 별도 허가 또는 상업 사용 가능한 대체 모델이 필요합니다.

AudioScoreTool은 MuScriptor weights를 자체 배포하지 않습니다.

---

# 테스트

```bash
uv sync --extra dev
uv run ruff check src tests scripts
uv run pytest -q
```

CI 검증 범위:

- Python lint / unit / integration test
- fixture 기반 전체 transcription orchestration
- 자동 코드 분석
- MusicXML 구조 편집
- Revision / Undo
- API validation / localhost origin protection
- React / TypeScript production build
- Tauri Rust shell
- Windows / macOS / Linux 실제 desktop bundle

---

# 상세 문서

- [`docs/ARCHITECTURE.ko.md`](docs/ARCHITECTURE.ko.md) — 파이프라인·프로세스 구조
- [`docs/EDITOR.ko.md`](docs/EDITOR.ko.md) — MusicXML 편집·Revision·출판 조판
- [`docs/BENCHMARK.ko.md`](docs/BENCHMARK.ko.md) — 모델 비교와 평가 지표

---

## 프로젝트 상태

v0.6은 기능 구현 위에 **상용 데스크탑 제품 수준의 정보구조·온보딩·한국어 UX·상태 표시·디자인 시스템**을 정리하는 Product UI 릴리스입니다.

실제 채보 품질은 음원 특성, 모델 크기, 하드웨어, 보컬/악기 구성에 따라 달라질 수 있으므로 대표 음원을 이용한 로컬 Benchmark를 권장합니다.
