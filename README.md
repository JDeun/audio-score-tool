# AudioScoreTool

AudioScoreTool은 완성된 음원 또는 YouTube 영상을 입력으로 받아 **다중 파트 악보를 자동 생성하고, 곡 단위로 관리하며, 앱 안에서 수정·조판한 뒤 출판용 PDF/MusicXML/MIDI로 내보내는 로컬 우선 데스크탑 애플리케이션**입니다.

현재 버전: **v0.5.0**

```text
로컬 음원 / YouTube URL
        ↓
오디오 준비
        ↓
다중 악기 자동 채보
        ↓
자동 코드 추정 + 가사 정렬
        ↓
Full Score + 악기별 파트
        ↓
곡 라이브러리
        ↓
악보 미리보기 / 세부 수정 / 출판 조판
        ↓
PDF / MusicXML / MIDI
```

---

## 핵심 원칙

AudioScoreTool은 사용자가 처음부터 악보를 입력하는 프로그램이 아닙니다.

**AI가 먼저 최대한 완성된 악보를 생성하고, 사용자는 틀린 부분과 출판 디테일만 수정하는 흐름**을 기본으로 합니다.

자동 생성 대상:

- 보컬/Voice
- 피아노/Keyboard
- 기타
- 베이스
- 드럼
- 그 외 MuScriptor가 감지한 악기 파트
- 코드 심벌
- 가사
- Full Score
- 파트별 MusicXML/PDF

음원에 없는 악기를 임의로 추가하지 않고, 모델이 감지한 실제 파트를 기준으로 악보를 생성합니다.

---

# 입력

## 로컬 파일

지원 형식:

- WAV
- MP3
- FLAC
- M4A
- AAC
- OGG
- OPUS
- WEBM

## YouTube

앱의 YouTube Import에서 URL을 입력하면:

1. URL 검증
2. 제목/채널/길이 확인
3. yt-dlp로 오디오 준비
4. 기존 자동 채보 파이프라인 실행

지원 URL:

- 일반 YouTube 영상
- `youtu.be`
- Shorts
- Live
- YouTube Music
- Embed

한 번에 한 곡을 관리하는 제품 흐름을 유지하기 위해 재생목록 일괄 처리는 의도적으로 지원하지 않습니다.

YouTube 콘텐츠는 사용자가 다운로드·처리 권한을 가진 경우에만 사용해야 합니다.

---

# 자동 채보 파이프라인

```text
Audio
  ↓
MuScriptor
  ├─ 다중 악기 note event 추정
  ├─ MIDI
  └─ MusicXML
       ↓
  자동 화성 분석
       ↓
  MusicXML <harmony> 코드 심벌

Audio
  ↓
Demucs
  ↓
vocals.wav
  ↓
WhisperX
  ↓
가사 + word timestamp
  ↓
보컬 노트에 가사 정렬

최종 MusicXML
  ↓
MuseScore
  ├─ Full Score PDF/MIDI
  └─ 감지된 악기별 MusicXML/PDF
```

## 자동 코드

MuScriptor가 추출한 피아노/기타/베이스/보컬 등 pitched part의 음들을 시간축으로 종합해 코드 후보를 추정하고 MusicXML `<harmony>`로 삽입합니다.

예:

```text
| C       Am7      | F       G/B      |
| C/E     F        | Dm7     G7       |
```

지원하는 대표 코드 품질:

- Major / Minor
- 6 / m6
- 7 / maj7 / m7
- 9 / maj9 / m9
- sus2 / sus4
- dim / dim7
- aug
- m7b5
- slash chord

자동 화성 분석은 사람이 판정한 코드와 항상 일치한다고 보장하지 않습니다. 앱의 코드 Inspector는 **자동 생성 코드를 보정하기 위한 기능**입니다.

---

# 곡 라이브러리

실행 이력인 Job과 실제 편집 대상인 Song을 구분합니다.

```text
Song
├─ 제목 / 아티스트 메모
├─ 원본 MusicXML
├─ 현재 MusicXML
├─ 자동 코드
├─ 감지된 악기 파트
├─ 출판 설정
├─ Revision
├─ 수정 이력
└─ Export
```

곡을 삭제하면 해당 Job으로부터 다시 자동 생성되지 않도록 tombstone을 유지합니다.

---

# 악보 미리보기

OpenSheetMusicDisplay(OSMD)로 현재 MusicXML을 앱 안에서 SVG 악보로 렌더링합니다.

- PDF 생성 전 실시간 확인
- 확대/축소
- 파트명 표시
- 가사 표시
- 코드 심벌 표시
- 제목/크레딧 표시
- 페이지/시스템 나눔 확인

편집은 SVG 자체를 임의로 변형하는 방식이 아니라 **MusicXML 구조를 Inspector에서 수정하고 동일 MusicXML을 다시 렌더링하는 방식**입니다. 따라서 미리보기와 최종 Export가 서로 다른 데이터를 사용하는 문제를 피합니다.

---

# 노트 편집

선택한 노트/쉼표에서 다음을 수정할 수 있습니다.

## 음정

- A-G
- 더블 플랫
- 플랫
- 내추럴
- 샵
- 더블 샵
- 옥타브

## 리듬

- 온음표
- 2분음표
- 4분음표
- 8분음표
- 16분음표
- 32분음표
- 64분음표
- 1점음표
- 2점음표

현재 MusicXML의 `divisions`로 정확히 표현할 수 없는 리듬 조합은 잘못된 MusicXML을 만드는 대신 편집을 거부합니다.

## 노트/쉼표

- 기존 노트 → 쉼표 변환
- 쉼표 → 노트 변환
- 선택 위치 앞에 음표/쉼표 삽입
- 선택 위치 뒤에 음표/쉼표 삽입
- 선택 음표 삭제

마디의 마지막 음표를 무작정 삭제해 빈 마디를 만드는 대신, 필요하면 마디 삭제 또는 쉼표 변환을 사용합니다.

## 가사

선택 노트에 연결된 가사를 수정하거나 제거할 수 있습니다.

## 표현기호

- Staccato
- Tenuto
- Accent
- Marcato / Strong Accent
- Tie start / stop
- Slur start / stop
- Beam begin / continue / end
- Forward hook / Backward hook

MusicXML의 실제 `notations`, `tie`, `beam` 요소를 수정합니다.

---

# 마디 · 조표 · 박자표 편집

Full Score에서 특정 마디를 선택해 다음을 수정할 수 있습니다.

- 조표: fifths -7 ~ +7
- Major / Minor
- 박자 분자
- 박자 분모: 1 / 2 / 4 / 8 / 16 / 32
- 선택 마디 뒤 새 마디 삽입
- 선택 마디 삭제

다중 파트 악보에서 구조가 어긋나지 않도록 **마디 삽입·삭제와 조표/박자표 변경은 모든 파트에 같은 위치로 적용**됩니다.

새 마디는 현재 박자에 맞는 전마디 쉼표로 생성됩니다.

---

# 코드 수정

자동 생성된 코드 중 틀린 위치를 선택해 수정합니다.

예:

```text
C
Cm
C7
Cmaj7
Cm7
C9
Cmaj9
Csus4
Cdim7
F#m7b5
Bb7
G/B
```

코드는 음표 시점에 anchor되므로 한 마디 안에서도 여러 번 바꿀 수 있습니다.

---

# 출판용 조판

상용 악보 사이트에서 판매하는 악보에 가까운 페이지 구성을 만들기 위한 설정입니다.

## 페이지

- A4 / Letter
- 세로 / 가로
- 위/아래/왼쪽/오른쪽 여백

## 시스템

- 한 줄당 마디 수
- 한 페이지당 악보 줄(System) 수
- 시스템 간격
- 첫 페이지 제목 영역 높이

예:

```text
한 줄 4마디
페이지당 5줄
→ 약 20마디 / 페이지
```

MusicXML의 `new-system`, `new-page`, `system-layout`, `page-layout` 등을 이용해 조판 정보를 저장합니다.

## 첫 페이지 제목/크레딧

- 제목
- 부제 / 버전
- 작곡
- 작사
- 편곡
- 저작권 / 출처
- 제목 글자 크기
- 부제 글자 크기
- 크레딧 글자 크기

이 정보는 화면 오버레이가 아니라 MusicXML의 `credit`, `identification`, `rights`에 기록됩니다.

---

# Revision / Undo

악보 변경 전 현재 상태를 snapshot합니다.

Revision 대상:

- 음정
- 리듬
- 노트/쉼표 삽입·삭제
- 마디 삽입·삭제
- 조표/박자표
- 가사
- 코드
- 타이/슬러/빔/아티큘레이션
- 제목
- 출판 레이아웃
- 크레딧

구조 편집은 한 번의 사용자 저장을 하나의 Revision으로 처리하도록 API를 원자적으로 구성합니다.

`실행 취소`는 MusicXML과 해당 시점의 출판 설정을 함께 되돌립니다.

`원본 복원`은 자동 채보 원본으로 악보 내용을 복원한 뒤 현재 출판 설정을 다시 적용합니다.

---

# Export

현재 Revision에서 생성:

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
└─ 기타 감지 파트
```

악보가 수정되면 이전 PDF/MIDI/파트 Export는 자동 무효화됩니다.

따라서 구버전 파일을 현재 악보로 착각해 배포하는 것을 방지합니다.

---

# 모델 Benchmark

같은 음원을 여러 모델 조합으로 비교할 수 있습니다.

- MuScriptor small / medium / large
- WhisperX 조합
- 실행 시간
- 성공/실패
- 가사 attachment ratio
- Note Precision / Recall / F1
- Onset MAE

Ground Truth MIDI가 있으면 reference 기반 지표를 계산합니다.

CLI:

```bash
uv run audio-score benchmark song.wav \
  --language ko \
  --profile all \
  --reference-midi reference.mid
```

---

# 실행 환경

| 환경 | MuScriptor | Demucs | WhisperX |
|---|---|---|---|
| NVIDIA GPU | CUDA | CUDA | CUDA / FP16 |
| Apple Silicon | MPS | CPU | CPU / INT8 |
| CPU only | CPU | CPU | CPU / INT8 |

Auto 프리셋 기본값:

- CPU only → `fast`
- Apple Silicon → `balanced`
- NVIDIA CUDA → `balanced`

실제 최적 조합은 앱의 Benchmark로 측정해 확정하는 것을 권장합니다.

---

# 사용자가 직접 해야 하는 부분

다음은 계정 또는 실제 하드웨어 소유자만 수행할 수 있습니다.

1. Hugging Face에서 MuScriptor 모델 라이선스 수락
2. 로컬 Hugging Face 인증
3. MuseScore 4 설치
4. 실제 사용하는 CPU/GPU/Mac에서 모델 다운로드 및 첫 inference
5. 대표 음원으로 실제 품질 Benchmark
6. 공개 배포 시 Apple/Windows 코드서명 자격증명 제공

Hugging Face 인증:

```bash
uvx hf auth login
```

AudioScoreTool은 Hugging Face 토큰 값을 UI에 노출하거나 자체 저장하지 않습니다.

---

# 라이선스 주의

AudioScoreTool 프로젝트 코드의 라이선스와 외부 모델 가중치 라이선스는 별개입니다.

현재 공개 MuScriptor 모델 weights는 **CC BY-NC 4.0**입니다. 따라서 현재 weights를 그대로 상업 서비스/유료 제품에 재배포하려면 upstream의 별도 허가 또는 상업 사용 가능한 대체 모델이 필요합니다.

---

# 개발 실행

```bash
git clone https://github.com/JDeun/audio-score-tool.git
cd audio-score-tool
uv sync --extra dev
```

데스크탑 개발:

```bash
cd desktop
npm install
npm run desktop:dev
```

---

# 데스크탑 빌드

```bash
uv sync --extra desktop
cd desktop
npm install
npm run desktop:build
```

빌드 과정:

1. 플랫폼별 아이콘 생성
2. Python/FastAPI backend PyInstaller sidecar 생성
3. Tauri desktop bundle 생성

모델 weights와 MuseScore는 라이선스/용량 문제 때문에 앱 설치 파일에 재배포하지 않습니다.

---

# CI

GitHub Actions에서 검증:

- Ruff
- Python unit/integration tests
- fixture 기반 전체 파이프라인
- 자동 코드 추정
- 파트 분리
- MusicXML pitch/lyric editing
- 리듬/쉼표/삽입/삭제 편집
- 마디/조표/박자표 편집
- 타이/슬러/빔/아티큘레이션 편집
- Revision / Undo
- 출판 레이아웃
- React / TypeScript build
- Vite production build
- Tauri Rust shell
- Windows desktop bundle
- macOS desktop bundle
- Linux desktop bundle

실제 gated 모델의 음악적 정확도는 사용자 인증과 실제 target hardware가 필요하므로 내장 Benchmark에서 수행합니다.

---

# 편집 방식에 대한 범위

AudioScoreTool의 내장 편집기는 **OSMD를 렌더러로 사용하고 MusicXML을 구조적으로 수정하는 Inspector 방식**입니다.

즉 SVG 음표를 마우스로 자유롭게 끌어 배치하는 별도의 작곡 프로그램을 구현하는 것이 아니라, 자동 채보 결과를 수정하고 판매 가능한 형태로 조판하는 목적에 맞춰 MusicXML을 직접 수정합니다.

이 방식의 장점은 미리보기, MusicXML, MuseScore PDF/MIDI가 항상 같은 악보 데이터를 공유한다는 점입니다.
