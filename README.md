# AudioScoreTool

> **음원 한 곡을 출판 가능한 악보로.**  
> 로컬 음원이나 YouTube 링크를 넣으면 다중 악기 채보, 코드·가사 정렬, 악보 수정, 출판 조판까지 한 앱에서 처리하는 로컬 우선 데스크탑 악보 제작 도구입니다.

**현재 버전: v0.7.0**

---

## 무엇을 하나요?

```text
음원 파일 / YouTube URL
          ↓
 MR-MT3 다중 악기 자동 채보
          ↓
보컬 · 피아노 · 기타 · 베이스 · 드럼 · 기타 감지 파트
          ↓
자동 코드 심벌 · 가사 인식/정렬
          ↓
      곡 라이브러리
          ↓
미리보기 · 세부 수정 · 출판 조판
          ↓
PDF · MusicXML · MIDI · 파트보
```

AudioScoreTool의 기본 원칙은 단순합니다.

> **AI가 먼저 최대한 완성된 악보를 만들고, 사용자는 틀린 부분과 출판 디테일만 수정합니다.**

처음부터 음표나 코드를 사람이 입력하는 프로그램이 아닙니다.

---

## 주요 기능

### 자동 생성

- 완성된 믹스 음원에서 다중 악기 자동 채보
- 보컬 / 피아노·키보드 / 기타 / 베이스 / 드럼 등 감지된 파트 생성
- Full Score + 악기별 파트보 생성
- 자동 코드 진행 추정 및 오선 위 코드 심벌 삽입
- Demucs + WhisperX 기반 가사 인식 및 vocal-like part 정렬
- 로컬 파일 / YouTube URL 입력
- 교체 가능한 채보 provider 구조

### 악보 편집

- MusicXML 기반 앱 내 실시간 미리보기
- 음정 / 옥타브 / 샵·플랫
- 온음표 ~ 64분음표 / 점음표
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
- 제목 / 부제 / 작곡 / 작사 / 편곡 / 저작권·출처
- Full Score 및 파트별 PDF / MusicXML

### 데스크탑 제품 기능

- `새 악보 / 곡 라이브러리 / 작업 내역 / 성능 비교 / 설정` 단일 내비게이션
- 첫 실행 온보딩
- CUDA / Apple Metal(MPS) / CPU 자동 감지
- 작업 큐 및 동시 GPU 작업 방지
- 실행 중 전체 프로세스 트리 취소
- SQLite 작업 히스토리
- 실패 작업 재실행
- 출력 폴더 열기
- 저장공간 정리
- Windows / macOS / Linux 패키징

---

# v0.7 채보 엔진

AudioScoreTool은 채보 엔진을 제품 코드와 분리했습니다.

| 엔진 | 역할 | 모델 학습 필요 | 상업화 관점 |
|---|---|---:|---|
| **MR-MT3 via MT3-Infer** | **기본 권장** 다중 악기 채보 | 아니오 | MT3-Infer MIT, MR-MT3 코드/공개 checkpoint MIT 표기 |
| **YourMT3+ via MT3-Infer** | 고품질 비교·실험 | 아니오 | checkpoint 배포본은 Apache-2.0 표기지만 upstream 코드 표기가 달라 출시 전 재검토 권장 |
| **AudioScore Native** | 장기 R&D / 완전한 모델 소유 | 예 | project-owned checkpoint 목표 |
| **MuScriptor** | 호환 / 연구 / 비교 | 아니오 | 공개 weights 비상업 조건이므로 상용 기본값에서 제외 |

기본 설정은 다음과 같습니다.

```text
provider = mt3_infer
model    = mr_mt3
```

MT3-Infer는 `0.2.0`을 기본 runtime revision으로 고정하며, MR-MT3 checkpoint는 첫 사용 시 upstream에서 로컬 캐시로 자동 다운로드합니다. 별도의 자체 모델 학습은 필요하지 않습니다.

> 이 문서는 기술적 라이선스 점검을 기록한 것이며 법률 자문을 대체하지 않습니다. 유료 배포 직전에는 고정된 runtime/checkpoint revision과 THIRD_PARTY_NOTICES를 다시 확인해야 합니다.

---

# 빠른 시작

## 1. 저장소 준비

```bash
git clone https://github.com/JDeun/audio-score-tool.git
cd audio-score-tool
uv sync --extra dev
```

MT3-Infer를 프로젝트 환경에 직접 설치하려면:

```bash
uv sync --extra mt3
```

설치하지 않아도 `uvx`가 있으면 AudioScoreTool이 고정된 `mt3-infer[torch]==0.2.0` runtime을 실행할 수 있습니다.

## 2. MuseScore 4 설치

MR-MT3는 다중 트랙 MIDI를 만들고, AudioScoreTool이 MuseScore를 외부 프로세스로 호출해 MusicXML과 PDF를 생성합니다.

앱이 MuseScore를 자동으로 찾지 못하면 설정 화면에서 실행 파일 경로를 지정할 수 있습니다.

## 3. 데스크탑 앱 실행

```bash
cd desktop
npm install
npm run desktop:dev
```

기본 MR-MT3 경로에서는 **MuScriptor Hugging Face 라이선스 승인도, 자체 모델 학습도 필요하지 않습니다.** 첫 채보 시 checkpoint 다운로드 때문에 평소보다 시간이 더 걸릴 수 있습니다.

---

# 채보 엔진 설정

## MR-MT3 — 기본 권장

```bash
export AST_TRANSCRIPTION_ENGINE=mt3_infer
export AST_MT3_MODEL=mr_mt3
```

외부 CLI를 직접 고정하려면:

```bash
export AST_MT3_INFER_CMD=mt3-infer
```

## YourMT3+ — 품질 비교용

```bash
export AST_TRANSCRIPTION_ENGINE=mt3_infer
export AST_MT3_MODEL=yourmt3
```

다중 파트 품질 비교에 사용할 수 있지만, 상용 릴리스 기본값으로 고정하기 전 upstream 라이선스 provenance를 다시 확인하세요.

## MuScriptor — 호환용

```bash
export AST_TRANSCRIPTION_ENGINE=muscriptor
uvx hf auth login
```

공개 MuScriptor weights의 비상업 조건 때문에 상용 기본 provider로 사용하지 않습니다.

## AudioScore Native — 선택적 R&D

```bash
uv sync --extra native
export AST_TRANSCRIPTION_ENGINE=native
export AST_NATIVE_CHECKPOINT=/path/to/audio-score-native.pt
```

일반 사용자는 Native 모델을 학습할 필요가 없습니다. 이 경로는 장기적으로 외부 checkpoint까지 제거하고 모델 weights를 직접 소유해야 할 때를 위한 연구 경로입니다.

자세한 내용: [`docs/NATIVE_MODEL.ko.md`](docs/NATIVE_MODEL.ko.md)

---

# 사용 흐름

## 새 악보 — 로컬 파일

1. WAV / MP3 / FLAC / M4A 등의 음원 선택 또는 드래그 앤 드롭
2. 채보 엔진과 가사 옵션 확인
3. **자동 채보 시작**
4. 완료 후 **곡 라이브러리에서 편집**

## 새 악보 — YouTube

1. `새 악보 → YouTube 링크`
2. URL 입력
3. 제목·채널·재생시간 확인
4. 콘텐츠 처리 권한 확인
5. 자동 채보 시작

재생목록 일괄 처리는 지원하지 않습니다. 사용자가 다운로드·처리 권한을 가지고 있거나 YouTube/권리자가 허용한 콘텐츠에만 사용해야 합니다.

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

실제 모델이 감지한 파트를 기준으로 생성하며, 음원에 없는 악기를 임의로 추가하지 않습니다.

---

# 자동 코드와 가사

채보된 pitched part를 시간축으로 합산해 화성을 추정하고 MusicXML `<harmony>`로 저장합니다.

```text
| C        Am7      | F        G/B      |
| C/E      F        | Dm7      G7       |
```

코드 Inspector는 처음부터 코드를 입력하는 화면이 아니라 **자동 분석 결과를 보정하는 화면**입니다.

가사가 포함된 곡은 Demucs로 보컬을 분리한 뒤 WhisperX word timing을 MusicXML의 vocal-like part에 정렬합니다.

---

# 곡 라이브러리와 편집기

완료된 채보는 Job이 아니라 Song 단위로 관리합니다.

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

OpenSheetMusicDisplay(OSMD)가 현재 MusicXML을 앱 안에서 렌더링합니다. MusicXML을 single source of truth로 유지하며, 수정하면 이전 PDF/MIDI/파트보를 구버전 처리하고 현재 Revision에서 다시 Export합니다.

---

# 성능 비교

앱의 성능 비교에서는 다음을 구분해 실행할 수 있습니다.

- MR-MT3
- YourMT3+
- MuScriptor small / medium / large
- AudioScore Native(checkpoint가 있을 때)

Ground Truth MIDI 없이:

- 처리 시간
- 성공 여부
- 가사 attachment ratio

Ground Truth MIDI가 있으면 추가로:

- Note Precision
- Note Recall
- Note F1
- Onset MAE

를 계산합니다.

---

# AudioScore Native는 왜 남겨두나요?

MR-MT3 공개 checkpoint를 사용할 수 있으므로 **지금 당장 자체 모델을 처음부터 학습할 필요는 없습니다.**

다만 장기적으로 외부 checkpoint 자체를 전혀 사용하지 않는 제품이 필요할 수 있어 Native 학습/추론 골격을 별도 R&D 경로로 유지합니다.

저장소에는 다음이 포함됩니다.

- multi-instrument event vocabulary
- MIDI ↔ event codec
- log-Mel frontend
- Transformer encoder/decoder
- CUDA / MPS / CPU inference
- `audio-score-native` CLI
- `audio-score-native-v1` checkpoint 포맷
- manifest 기반 training loop
- validation / best checkpoint
- training-license allowlist
- Slakh2100 manifest 준비 도구

학습 manifest는 비상업 라이선스 데이터를 자동 거부합니다. 이는 앱 사용의 선행조건이 아닙니다.

---

# 데스크탑 빌드

```bash
uv sync --extra desktop
cd desktop
npm install
npm run desktop:build
```

GitHub Actions는 Windows / macOS / Linux unsigned bundle을 생성하도록 구성되어 있습니다. 코드서명/notarization은 소유자 인증서가 필요한 별도 배포 단계입니다.

---

# 라이선스 / 제3자 구성요소

AudioScoreTool 코드와 외부 모델 weights의 라이선스는 별개로 관리합니다.

- MT3-Infer: MIT
- MR-MT3 원 구현: MIT
- MR-MT3 공개 Hugging Face checkpoint: MIT 표기
- YourMT3+ checkpoint 배포본: Apache-2.0 표기, upstream 코드 provenance 재검토 권장
- MuScriptor 공개 weights: 비상업 조건으로 상용 기본 경로에서 제외
- AudioScore Native: project-owned checkpoint 목표

자세한 provenance와 배포 전 확인사항은 [`docs/THIRD_PARTY_LICENSES.ko.md`](docs/THIRD_PARTY_LICENSES.ko.md)를 참고하세요.

---

# 문서

- [아키텍처](docs/ARCHITECTURE.ko.md)
- [악보 편집기](docs/EDITOR.ko.md)
- [벤치마크](docs/BENCHMARK.ko.md)
- [AudioScore Native](docs/NATIVE_MODEL.ko.md)
- [제3자 모델·라이선스](docs/THIRD_PARTY_LICENSES.ko.md)

---

# 테스트

```bash
uv sync --extra dev
uv run ruff check src tests training scripts
uv run pytest -q
```

Native 모델 학습 코드를 실제 실행할 때만:

```bash
uv sync --extra native
```

---

## 현재 제품 철학

AudioScoreTool은 **AI 자동 생성 → 사람이 세부 보정 → 출판 가능한 결과물**이라는 흐름을 목표로 합니다.

현재 기본 엔진은 학습 부담이 없는 MR-MT3이며, 자체 AudioScore Native는 향후 완전한 모델 소유가 필요할 때 선택할 수 있는 별도 경로입니다.
