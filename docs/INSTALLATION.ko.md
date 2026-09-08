# 설치 및 첫 실행 설계

AudioScoreTool의 설치 목표는 다음입니다.

> **새 PC에서 설치 파일 하나를 실행한 뒤, CLI 지식 없이 첫 악보를 만들 수 있어야 합니다.**

## 사용자에게 요구하지 않는 것

일반 사용자는 다음을 알 필요가 없어야 합니다.

- `pip`, `uv`, `npm`, `cargo` 사용법
- Python/Node/Rust 개발환경 구성
- PATH 수동 편집
- 개별 Python package의 가상환경 관리

Desktop package는 앱과 Python orchestration sidecar를 함께 배포하는 것을 전제로 합니다. 개발 명령은 저장소 개발자용입니다.

AI 도구를 격리 실행할 때 `uv/uvx`가 필요한 환경에서는 Setup Center가 이를 **관리형 AI 런타임**으로 취급합니다. 사용자가 Python 환경을 직접 구성하는 방식으로 안내하지 않습니다.

## Setup Center

첫 실행 소개 온보딩이 끝난 뒤 기본 채보 환경이 준비되지 않았다면 Setup Center가 이어서 열립니다. 두 모달이 겹치지 않도록 순차 실행합니다. 이후 우측 하단 `설치 도우미`에서 언제든 다시 열 수 있습니다.

구성요소는 세 단계로 나눕니다.

### 필수

기본 목표:

```text
음원 → 자동 채보 → 편집 가능한 MusicXML
```

- 선택된 transcription engine
- 필요 시 관리형 `uv/uvx` 런타임
- MuScriptor 사용 시 Hugging Face 인증과 모델 준비

만 기본 사용에 직접 영향을 줍니다.

### 권장

```text
기본 채보 + 가사 + PDF 출판
```

- WhisperX: 가사 인식/정렬
- LilyPond + musicxml2ly: PDF 생성

가사를 사용하지 않거나 PDF가 당장 필요 없다면 설치하지 않아도 기본 채보는 가능합니다.

### 선택

- Audiveris: PDF/이미지 OMR
- FFmpeg + FluidSynth + SoundFont: Audio evidence 검증
- LLM/Vision API: 보조 검증
- Chromaprint/fpcalc: 사용자가 요청한 원음 fingerprint 기반 곡 식별

이 기능들이 없어도 기본 채보/편집은 `준비 안 됨`으로 취급하지 않습니다.

## MuseScore 비의존 정책

AudioScoreTool은 MuseScore 실행 파일이나 MuseScore CLI를 호출하지 않습니다.

```text
앱 내 미리보기       OSMD
MIDI ↔ MusicXML      music21
MusicXML → PDF        LilyPond + musicxml2ly
PDF/이미지 → MusicXML Audiveris
파트 분리             AudioScoreTool 자체 MusicXML 처리
```

따라서 MuseScore 설치 여부는 Setup Center readiness, PDF export 가능 여부, 채보 가능 여부에 영향을 주지 않습니다.

## 자동 설치 정책

앱이 임의의 shell command를 조합해 실행하지 않습니다. 운영체제별로 검토된 고정 package-manager recipe만 사용합니다.

### macOS

Homebrew가 이미 설치되어 있을 때 Setup Center에서 다음을 자동 실행할 수 있습니다.

```bash
brew install uv
brew install ffmpeg
brew install fluid-synth
brew install lilypond
```

Finder에서 실행한 GUI 앱은 터미널과 PATH가 다를 수 있으므로 `/opt/homebrew/bin`, `/usr/local/bin` 등 일반 설치 위치도 직접 탐색합니다.

### Windows

winget이 있을 때 현재 검증된 FFmpeg package ID만 자동 설치 대상으로 둡니다.

```powershell
winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
```

다른 구성요소는 package ID와 배포 경로를 충분히 고정할 수 있을 때만 자동 설치 대상으로 추가합니다.

### Linux

배포판마다 package manager와 package version이 크게 다르므로 현재 자동 관리자 설치를 강제하지 않습니다. 공식 다운로드 또는 사용 중인 배포판 package manager를 사용합니다.

## AI 모델 관리자

앱의 `AI 모델` 창에서 MuScriptor 모델을 별도로 관리합니다.

제공 정보:

- Small / Medium / Large 모델
- parameter 규모
- 예상 weights 용량
- 실제 로컬 cache 사용량
- 현재 선택 모델
- 남은 디스크 공간
- 라이선스
- 상용 모드 사용 가능 여부

정책:

```text
자동 다운로드 = OFF
명시적 사용자 동의 후 다운로드
상용 모드에서 MuScriptor 다운로드/선택 차단
```

MuScriptor 공개 weights는 CC BY-NC 4.0이므로 개인/비상업 모드에서만 모델 관리자에 의해 준비할 수 있습니다.

Large는 정확도 우선 기본값이며 weights가 약 5.47 GB이므로 다운로드 전 여유 공간을 검사합니다.

### 다운로드 진행률

`hf download`를 background job으로 실행하고 Hugging Face cache 증가량을 기준으로 진행률을 표시합니다.

```text
MuScriptor Large 다운로드 중
3.9 GB / 약 5.5 GB
██████████████░░░░ 72%
```

완료된 모델은 다시 다운로드하지 않으며, 사용하지 않는 모델은 모델 관리자에서 cache를 제거할 수 있습니다.

## Hugging Face 인앱 인증

MuScriptor gated weights를 위해 인증은 필요하지만 사용자가 터미널 명령을 직접 실행하는 것을 기본 UX로 요구하지 않습니다.

흐름:

```text
1. 모델 라이선스 페이지 열기
2. 라이선스 수락
3. 앱에서 `로그인 시작`
4. Hugging Face 공식 browser/device 인증
5. 앱에서 자동으로 인증 완료 확인
6. 모델 준비
```

인증은 Hugging Face 공식 `hf auth login` browser/device flow를 사용합니다. AudioScoreTool이 토큰 값을 입력받거나 자체 DB/settings에 저장하지 않습니다. 인증 token storage는 Hugging Face CLI가 `HF_HOME`에서 관리합니다.

## 공식 다운로드 fallback

자동 설치를 지원하지 않는 항목은 Setup Center에서 공식 배포 페이지를 제공합니다. Tauri opener를 사용해 시스템 기본 브라우저에서 엽니다.

- uv: `https://docs.astral.sh/uv/getting-started/installation/`
- LilyPond: `https://lilypond.org/download.html`
- Audiveris: `https://audiveris.github.io/audiveris/`
- FFmpeg: `https://ffmpeg.org/download.html`
- FluidSynth: `https://www.fluidsynth.org/download/`
- Hugging Face: `https://huggingface.co/`

설치 후 `다시 검사`를 누르면 readiness를 재평가합니다.

## LLM은 설치 항목이 아님

LLM/Vision validator는 기본 OFF이며 필수가 아닙니다.

사용하려면 둘 중 하나만 선택합니다.

```text
로컬 Ollama / vLLM / LM Studio
또는
HTTPS OpenAI-compatible hosted API
```

원격 API를 쓰는 경우 로컬 LLM 설치는 필요하지 않습니다.

## 상용 v1.0 이전 추가 목표

모델 관리자와 Setup Center까지 구현된 이후 남은 설치 UX의 핵심은 다음입니다.

1. Windows/macOS signed installer 실제 검증
2. 앱 번들에 포함할 수 있는 외부 runtime의 라이선스 검토
3. 설치 완료 후 sample score smoke test
4. 앱 업데이트와 DB/runtime migration 검증
5. MT3 계열 모델도 같은 Model Library UX로 통합
6. 다운로드 취소/재개와 불완전 cache 정리 고도화

외부 GPL/AGPL binary를 installer에 직접 번들하기 전에는 해당 배포 의무를 별도로 검토합니다.
