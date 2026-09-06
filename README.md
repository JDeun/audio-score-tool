# AudioScoreTool

AudioScoreTool은 완성된 음원 또는 YouTube 영상을 입력으로 받아 **악보를 자동 채보하고, 곡 단위로 관리하며, 미리보기·수정·조판 후 PDF/MusicXML/MIDI로 내보내는 로컬 우선 데스크탑 애플리케이션**입니다.

단순히 AI가 만든 초안을 다운로드하는 도구가 아니라 다음 흐름을 목표로 합니다.

```text
음원 / YouTube
      ↓
자동 채보
      ↓
곡 라이브러리
      ↓
악보 미리보기
      ↓
노트 / 가사 / 코드 수정
      ↓
출판 레이아웃 조정
      ↓
첫 페이지 제목·크레딧 구성
      ↓
최종 PDF / MusicXML / MIDI 생성
```

현재 버전: **v0.4.0**

---

## 주요 기능

### 입력

- 로컬 오디오 파일
  - WAV
  - MP3
  - FLAC
  - M4A
  - AAC
  - OGG
  - OPUS
  - WEBM
- YouTube URL
  - 일반 영상
  - Shorts
  - Live
  - YouTube Music
  - Embed URL
- YouTube 재생목록 일괄 처리는 현재 의도적으로 지원하지 않음

### 자동 채보

- MuScriptor 기반 악기/보컬 채보
- MIDI 생성
- MusicXML 생성
- PDF 악보 생성
- Demucs 기반 보컬 분리
- WhisperX 기반 가사 인식
- 가사-노트 정렬
- CUDA / Apple MPS / CPU 자동 실행 정책

### 곡 라이브러리

완료된 채보 Job은 별도의 `Song` 단위로 자동 등록됩니다.

```text
Song
├─ 곡 제목
├─ 아티스트 / 메모
├─ 원본 MusicXML
├─ 현재 편집 MusicXML
├─ 곡별 출판 설정
├─ Revision
├─ 수정 이력
├─ 코드 심벌
└─ 최종 Export
```

Job은 실행 이력이고 Song은 실제로 관리·편집하는 곡 단위입니다.

### 악보 미리보기

MusicXML은 OpenSheetMusicDisplay(OSMD)를 사용해 앱 내부에서 SVG 악보로 렌더링합니다.

PDF를 만들기 전에 현재 편집 상태를 바로 확인할 수 있습니다.

- 미리보기 확대/축소
- 수정 후 즉시 다시 렌더링
- 제목/크레딧 확인
- 코드 심벌 확인
- 시스템/페이지 나눔 확인

### 노트와 가사 편집

현재 지원하는 노트 단위 수정:

- 음 이름 A-G
- 더블 플랫 / 플랫 / 내추럴 / 샵 / 더블 샵
- 옥타브
- 노트에 연결된 가사

현재 리듬 길이, 쉼표 추가/삭제, 마디 추가/삭제, 조표/박자표를 GUI에서 직접 편집하는 기능은 아직 포함하지 않습니다.

### 코드 심벌

선택한 음표의 시점 위에 MusicXML `<harmony>` 코드 심벌을 삽입합니다.

예:

```text
C
Cm
C7
Cmaj7
Cm7
C6
Cm6
C9
Cmaj9
Cm9
Csus2
Csus4
Cdim
Cdim7
Caug
Cm7b5
F#maj7
Bb7
G/B
```

코드는 특정 음표 시점에 연결되므로 한 마디 안에서도 여러 번 바꿀 수 있습니다.

```text
| C        Am7       | F        G7        |
  1박      3박         1박      3박
```

MusicXML에서는 실제 `<harmony placement="above">` 요소로 저장되므로 OSMD 미리보기와 MuseScore PDF 출력이 같은 악보 데이터를 사용합니다.

---

# 출판용 악보 조판

AudioScoreTool v0.4에서는 상용 악보 사이트에서 판매하는 악보처럼 페이지 레이아웃을 조정할 수 있는 출판 설정을 제공합니다.

## 한 줄당 마디 수

예:

```text
한 줄당 4마디
| 1 | 2 | 3 | 4 |
| 5 | 6 | 7 | 8 |
```

MusicXML의 `new-system`을 사용해 시스템 나눔을 저장합니다.

## 한 페이지당 악보 줄 수

예:

```text
한 줄 4마디
페이지당 5줄
→ 약 20마디 / 페이지
```

MusicXML의 `new-page`를 사용해 페이지 나눔을 저장합니다.

## 줄 간격

악보 시스템 간 세로 간격을 mm 단위로 조정할 수 있습니다.

일반 문서의 행간에 해당하는 설정입니다.

## 페이지 여백

각 곡마다 다음 값을 따로 저장합니다.

- 위
- 아래
- 왼쪽
- 오른쪽

지원 용지:

- A4
- Letter

지원 방향:

- 세로
- 가로

## 첫 페이지 제목 영역

첫 페이지의 악보 시작 위치를 아래로 내리고 상단에 출판용 제목 영역을 구성할 수 있습니다.

지원 항목:

- 곡 제목
- 부제 / 버전
- 작곡
- 작사
- 편곡
- 저작권 / 출처
- 제목 글자 크기
- 부제 글자 크기
- 크레딧 글자 크기

예:

```text
                  My Song
               Piano & Vocal

                              작곡  Composer
                              작사  Lyricist
                              편곡  Arranger

──────────────────────────────────────
             악보 시작
```

이 정보는 단순 화면 오버레이가 아니라 MusicXML의 `credit`, `identification`, `rights`에 기록됩니다.

따라서 현재 MusicXML과 최종 PDF의 출판 정보가 일치하도록 설계되어 있습니다.

---

# Revision과 실행 취소

악보가 수정되기 직전에 현재 MusicXML과 출판 설정을 함께 저장합니다.

```text
songs/<song-id>/
├─ original.musicxml
├─ score.musicxml
├─ publication.json
├─ revisions/
│  ├─ rev-0001.musicxml
│  ├─ rev-0001.publication.json
│  ├─ rev-0002.musicxml
│  ├─ rev-0002.publication.json
│  └─ ...
└─ exports/
```

Revision 대상:

- 노트 수정
- 가사 수정
- 코드 수정
- 곡 제목 변경
- 페이지 레이아웃 변경
- 제목/크레딧 변경

`실행 취소`를 누르면 악보 내용뿐 아니라 해당 시점의 출판 설정도 함께 복원됩니다.

`원본 복원`은 자동 채보 원본의 음악 내용을 복원하되 현재 출판 설정은 유지합니다.

---

# Export 일관성

편집 후 이전 PDF/MIDI가 그대로 남아 있으면 오래된 파일을 실수로 배포할 수 있습니다.

AudioScoreTool은 MusicXML이 변경되는 즉시 기존 PDF/MIDI Export를 무효화합니다.

```text
Revision 4
PDF 생성
   ↓
노트 또는 레이아웃 수정
   ↓
Revision 5
   ↓
Revision 4 PDF/MIDI 자동 폐기
   ↓
최종 파일 생성 필요
```

`최종 파일 생성`을 실행하면 현재 Revision의 MusicXML을 기준으로 MuseScore가 PDF와 MIDI를 다시 생성합니다.

---

# 전체 구조

```text
[입력]
 ├─ 로컬 음원
 └─ YouTube URL
       ↓
     yt-dlp
       ↓
   오디오 파일
       ↓
┌─────────────────────────────────────┐
│ MuScriptor                          │
│ → MIDI / MusicXML / 초안 PDF        │
└─────────────────────────────────────┘
       │
       └─ Demucs → vocals.wav
                     ↓
                  WhisperX
                     ↓
                가사 타이밍
                     ↓
                노트-가사 정렬
                     ↓
                Song Library
                     ↓
┌─────────────────────────────────────┐
│ Score Publishing Workspace          │
│                                     │
│ 노트 수정                            │
│ 가사 수정                            │
│ 코드 심벌                            │
│ 페이지 조판                          │
│ 제목 / 크레딧                        │
│ Revision / Undo                     │
└─────────────────────────────────────┘
                     ↓
                 MuseScore
                     ↓
          PDF / MusicXML / MIDI
```

데스크탑:

```text
Tauri 2
└─ React + TypeScript + Vite
   ├─ 채보
   ├─ YouTube 가져오기
   ├─ 벤치마크
   ├─ 작업 이력
   ├─ 설정
   └─ 곡 라이브러리
       └─ 악보 편집/출판 작업공간
            ├─ OSMD 미리보기
            ├─ 노트 편집
            ├─ 코드 편집
            ├─ 출판 레이아웃
            ├─ 제목/크레딧
            ├─ Revision
            └─ Export

Python FastAPI sidecar
├─ MuScriptor
├─ Demucs
├─ WhisperX
├─ yt-dlp
├─ MuseScore
├─ Job Store
├─ Song Store
├─ Publication Store
└─ MusicXML 편집 계층
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

실제 최적 조합은 내장 Benchmark 기능으로 확인하는 것을 권장합니다.

---

# 설치 전 사용자 작업

MuScriptor 모델 가중치는 공개 코드와 별도의 라이선스를 사용합니다.

현재 공개 MuScriptor 모델 weights는 **CC BY-NC 4.0**이며 Hugging Face에서 사용자가 직접 라이선스를 수락해야 합니다.

```bash
uvx hf auth login
```

필요 항목:

1. Hugging Face에서 MuScriptor 모델 라이선스 수락
2. Hugging Face 로컬 인증
3. MuseScore 4 설치
4. 필요 시 실행 파일 경로를 앱 Setup에서 지정

AudioScoreTool은 Hugging Face 토큰 값을 읽어 UI에 표시하거나 자체 저장하지 않습니다.

---

# 개발 실행

```bash
git clone https://github.com/JDeun/audio-score-tool.git
cd audio-score-tool
uv sync --extra dev
```

데스크탑 개발 모드:

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

1. 플랫폼별 앱 아이콘 생성
2. FastAPI backend를 PyInstaller sidecar로 패키징
3. Tauri 앱 빌드

모델 weights와 MuseScore 자체는 설치 파일에 재배포하지 않습니다.

---

# CI

GitHub Actions에서 다음을 검사합니다.

- Ruff
- Python 단위/통합 테스트
- MusicXML 편집 테스트
- 코드 심벌 테스트
- 출판 레이아웃 테스트
- Revision 테스트
- React / TypeScript build
- Vite production build
- Tauri Rust shell
- Windows 실제 desktop bundle
- macOS 실제 desktop bundle
- Linux 실제 desktop bundle

실제 gated 모델 품질 평가는 사용자 인증과 실제 하드웨어가 필요하므로 로컬 Benchmark에서 수행합니다.

---

# 모델 벤치마크

앱의 Benchmark 화면 또는 CLI에서 같은 음원을 여러 모델 조합으로 비교할 수 있습니다.

지원 지표:

- 실행 시간
- 성공/실패
- 가사 attachment ratio
- Note Precision
- Note Recall
- Note F1
- Onset MAE(ms)

Ground Truth MIDI를 넣으면 reference 기반 정량 지표가 추가됩니다.

CLI 예:

```bash
uv run audio-score benchmark song.wav \
  --language ko \
  --profile all \
  --reference-midi reference.mid
```

---

# 현재 범위와 한계

AudioScoreTool v0.4의 목표는 **자동 채보 결과를 판매용 악보에 가까운 형태로 보정·조판할 수 있는 데스크탑 작업공간**입니다.

현재 GUI에서 지원하지 않는 고급 편집:

- 리듬값 직접 변경
- 쉼표 삽입/삭제
- 음표 삽입/삭제
- 마디 삽입/삭제
- 조표 직접 편집
- 박자표 직접 편집
- 빔/슬러/아티큘레이션 세부 편집
- 마우스로 악보 음표 자체를 직접 드래그하는 WYSIWYG 편집

이 기능들은 MusicXML 구조상 확장 가능하지만, 현재 v0.4에서는 노트/가사/코드/출판 조판에 우선 집중합니다.

자동 채보 및 자동 가사 정렬 역시 최종 출판 전에 사람이 검토하는 것을 전제로 합니다.

---

# 라이선스 주의

AudioScoreTool 자체 코드와 각 외부 구성요소의 라이선스는 별도로 확인해야 합니다.

특히 MuScriptor 공개 모델 weights는 현재 **CC BY-NC 4.0**이므로 현재 weights를 포함한 상업 서비스 또는 유료 배포에는 별도의 검토가 필요합니다.

YouTube 입력 기능 역시 사용자가 다운로드·가공 권한을 보유한 콘텐츠에 대해서만 사용해야 합니다.
