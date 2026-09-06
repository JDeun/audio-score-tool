# AudioScoreTool

> **음원 한 곡을 출판 가능한 악보로.**  
> 로컬 음원이나 YouTube 링크를 넣으면 감지된 악기 파트, 코드, 가사를 자동으로 채보하고 앱 안에서 수정·조판해 PDF / MusicXML / MIDI로 내보내는 로컬 우선 데스크탑 악보 제작 도구입니다.

**현재 버전: v0.7.0**

---

## 무엇을 할 수 있나요?

```text
음원 파일 / YouTube URL
          ↓
   채보 엔진 선택
  ┌───────────────────┐
  │ AudioScore Native │  ← 상업화용 프로젝트 소유 모델 경로
  │ MuScriptor        │  ← 호환 provider
  └───────────────────┘
          ↓
   다중 악기 자동 채보
          ↓
보컬 · 피아노 · 기타 · 베이스 · 드럼 · 기타 감지 파트
          ↓
자동 코드 심벌 · 가사 정렬
          ↓
      곡 라이브러리
          ↓
미리보기 · 세부 편집 · 출판 조판
          ↓
PDF · MusicXML · MIDI · 파트보
```

AudioScoreTool의 기본 원칙은 **AI가 먼저 최대한 완성된 악보를 만들고, 사용자는 틀린 부분과 출판 디테일만 수정하는 것**입니다.

---

## 주요 기능

### 자동 채보

- 완성된 믹스 음원에서 다중 악기 자동 채보
- 보컬 / 피아노·키보드 / 기타 / 베이스 / 드럼 등 감지된 파트 생성
- Full Score와 악기별 파트보 생성
- 자동 코드 진행 추정 및 마디 위 코드 심벌 표기
- Demucs + WhisperX 기반 보컬 가사 인식·정렬
- 로컬 파일과 YouTube URL 입력
- 교체 가능한 채보 엔진 provider 구조

### 악보 편집

- MusicXML 기반 실시간 악보 미리보기
- 음정 / 옥타브 / 샵·플랫
- 온음표 ~ 64분음표, 점음표
- 음표 ↔ 쉼표
- 음표·쉼표 삽입 / 삭제
- 마디 삽입 / 삭제
- 조표 / 장·단조 / 박자표
- 가사 / 코드 심벌
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
- SQLite 작업 히스토리
- 실패 작업 재실행
- 출력 폴더 열기
- 저장공간 정리
- 로컬 실행 파일 / 채보 엔진 설정
- Windows / macOS / Linux 패키징

---

# v0.7: 교체 가능한 채보 엔진

AudioScoreTool은 채보 기능을 특정 모델 하나에 고정하지 않습니다.

현재 provider:

| 엔진 | 용도 | 상태 |
|---|---|---|
| **AudioScore Native** | 프로젝트 소유 상업화 경로 | 자체 checkpoint 필요 |
| **MuScriptor** | 호환·비교·개발용 provider | 공개 weights는 비상업 라이선스 |

두 엔진 모두 다음 공통 계약만 만족하면 이후 파이프라인을 그대로 사용합니다.

```text
score.mid
score.musicxml
full_score.pdf   # 선택
```

이후 단계인 자동 코드, 가사 정렬, 파트 분리, 악보 편집, 출판 조판, PDF export는 채보 엔진과 독립적입니다.

앱 우측 하단의 **채보 엔진** 설정에서 provider를 변경할 수 있습니다.

---

# AudioScore Native

AudioScore Native는 MuScriptor 공개 가중치에 종속되지 않기 위한 프로젝트 자체 AMT(Automatic Music Transcription) 경로입니다.

현재 저장소에는 다음이 구현되어 있습니다.

- multi-instrument autoregressive event vocabulary
- MIDI → event token encoder
- event token → MIDI decoder
- log-Mel audio frontend
- Transformer encoder / decoder 모델
- CUDA / MPS / CPU inference
- `audio-score-native` CLI
- project-owned checkpoint 포맷 `audio-score-native-v1`
- manifest 기반 학습 루프
- validation / best checkpoint 저장
- 학습 데이터 라이선스 allowlist
- Slakh2100 manifest 준비 도구
- 제품 채보 pipeline provider 통합

### Native 런타임 설치

```bash
uv sync --extra native
```

### Native 체크포인트 사용

```bash
export AST_TRANSCRIPTION_ENGINE=native
export AST_NATIVE_CHECKPOINT=/path/to/audio-score-native.pt
```

또는 데스크탑 앱의 **채보 엔진** 설정에서 체크포인트 경로를 지정할 수 있습니다.

자세한 내용은 [`docs/NATIVE_MODEL.ko.md`](docs/NATIVE_MODEL.ko.md)를 참고하세요.

---

# 학습 데이터 라이선스 정책

AudioScore Native는 **상업 사용 가능 여부가 명시된 데이터만 학습 manifest에 들어갈 수 있도록** 설계되어 있습니다.

현재 allowlist:

- CC-BY-4.0
- CC0-1.0
- MIT
- Apache-2.0
- project-owned

예를 들어 `CC-BY-NC-4.0` 데이터가 manifest에 들어가면 학습을 시작하지 않고 오류를 발생시킵니다.

초기 seed dataset으로는 Slakh2100의 mix + aligned MIDI 구조를 지원합니다. 실제 상용 모델을 만들 때는 데이터 출처, 저작권, 파생물 조건을 프로젝트 차원에서 별도로 검토해야 합니다.

---

# 빠른 시작

## 1. 저장소 준비

```bash
git clone https://github.com/JDeun/audio-score-tool.git
cd audio-score-tool
uv sync --extra dev
```

## 2. MuseScore 4 설치

최종 MusicXML/PDF 렌더링에는 MuseScore 4 이상이 필요합니다.

앱이 자동으로 찾지 못하면 설정에서 실행 파일 경로를 지정할 수 있습니다.

## 3. 채보 엔진 선택

### MuScriptor provider

MuScriptor 공개 weights를 사용할 경우 upstream Hugging Face 모델 라이선스를 직접 수락하고 인증해야 합니다.

```bash
uvx hf auth login
```

### AudioScore Native provider

프로젝트가 직접 학습한 checkpoint가 필요합니다.

```bash
uv sync --extra native
export AST_TRANSCRIPTION_ENGINE=native
export AST_NATIVE_CHECKPOINT=/path/to/audio-score-native.pt
```

## 4. 데스크탑 앱 실행

```bash
cd desktop
npm install
npm run desktop:dev
```

---

# 사용 흐름

## 새 악보

### 로컬 음원

1. WAV / MP3 / FLAC / M4A 등의 파일 선택 또는 드래그 앤 드롭
2. 채보 엔진 / 품질 프리셋 확인
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

채보된 pitched part의 음들을 시간축으로 종합해 화성을 추정하고 MusicXML `<harmony>`로 기록합니다.

예:

```text
| C        Am7      | F        G/B      |
| C/E      F        | Dm7      G7       |
```

코드 편집기는 자동 생성 결과를 처음부터 입력하기 위한 기능이 아니라 **틀린 화성을 보정하기 위한 Inspector**입니다.

---

# 곡 라이브러리와 편집기

완료된 채보는 Job이 아니라 Song 단위로 관리됩니다.

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

OpenSheetMusicDisplay(OSMD)가 현재 MusicXML을 앱 안에서 렌더링합니다.

MusicXML을 단일 source of truth로 유지하며, 수정 후에는 이전 PDF/MIDI/파트보를 구버전 처리하고 현재 Revision 기준으로 다시 Export합니다.

---

# 성능 비교

Ground Truth MIDI 없이:

- 처리 시간
- 성공 여부
- 가사 attachment ratio

Ground Truth MIDI를 제공하면:

- Note Precision
- Note Recall
- Note F1
- Onset MAE

을 추가 계산합니다.

Native checkpoint가 준비되면 동일 평가 계약에 연결해 MuScriptor와 직접 비교할 수 있습니다.

---

# 데스크탑 빌드

```bash
uv sync --extra desktop
cd desktop
npm install
npm run desktop:build
```

GitHub Actions는 Windows / macOS / Linux unsigned bundle을 생성합니다.

코드서명과 notarization은 소유자별 인증서가 필요한 별도 배포 단계입니다.

---

# 라이선스와 상업화

AudioScoreTool 자체 코드와 **외부 모델 가중치의 라이선스는 별개**입니다.

- MuScriptor 공개 model weights: 상업 배포 기본 엔진으로 사용하지 않음
- AudioScore Native: 프로젝트 소유 checkpoint를 목표로 함
- Native 학습 데이터: manifest allowlist + 별도 provenance 관리 필요

상업 배포를 위한 권장 구성은 다음과 같습니다.

```text
AudioScoreTool
   ↓
AudioScore Native
   ↓
상업 사용이 허용된 데이터로 독립 학습
   ↓
project-owned checkpoint
```

외부 모델의 비상업 weights를 fine-tuning/distillation으로 우회해 프로젝트 소유 모델처럼 취급하는 방식은 사용하지 않습니다.

---

# 문서

- [아키텍처](docs/ARCHITECTURE.ko.md)
- [악보 편집기](docs/EDITOR.ko.md)
- [벤치마크](docs/BENCHMARK.ko.md)
- [AudioScore Native](docs/NATIVE_MODEL.ko.md)

---

# 테스트

```bash
uv sync --extra dev
uv run ruff check src tests training scripts
uv run pytest -q
```

Native 실제 모델 실행/학습:

```bash
uv sync --extra native
```

실제 장시간 학습은 GPU와 데이터셋이 필요하기 때문에 일반 CI에서는 수행하지 않습니다.
