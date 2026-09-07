# 설치 및 첫 실행 설계

AudioScoreTool의 설치 목표는 다음입니다.

> **새 PC에서 설치 파일 하나를 실행한 뒤, CLI 지식 없이 첫 악보를 만들 수 있어야 합니다.**

## 사용자에게 요구하지 않는 것

일반 사용자는 다음을 알 필요가 없어야 합니다.

- `pip`, `uv`, `npm`, `cargo`
- Python/Node/Rust 개발환경 구성
- PATH 수동 편집
- 개별 Python package 설치

Desktop package는 앱과 Python sidecar를 함께 배포하는 것을 전제로 합니다. 개발 명령은 저장소 개발자용입니다.

## Setup Center

첫 실행 소개 온보딩이 끝난 뒤 기본 채보 환경이 준비되지 않았다면 Setup Center가 이어서 열립니다. 이후 우측 하단 `설치 도우미`에서 언제든 다시 열 수 있습니다.

구성요소는 세 단계로 나눕니다.

### 필수

기본 목표:

```text
음원 → 자동 채보 → 편집 가능한 MusicXML
```

선택한 transcription engine과, MuScriptor 사용 시 필요한 Hugging Face 인증만 기본 readiness를 막을 수 있습니다.

### 권장

```text
기본 채보 + 가사 + PDF 출판
```

- WhisperX: 가사 인식/정렬
- LilyPond: PDF 생성

가사를 사용하지 않거나 PDF가 당장 필요 없다면 설치하지 않아도 기본 채보는 가능합니다.

### 선택

- Audiveris: PDF/이미지 OMR
- FFmpeg + FluidSynth + SoundFont: Audio evidence 검증
- LLM/Vision API: 보조 검증
- MuseScore: notation compatibility fallback

이 기능들이 없어도 기본 채보/편집은 `준비 안 됨`으로 취급하지 않습니다.

## 자동 설치 정책

앱이 임의의 shell command를 만들거나 실행하지 않습니다. 운영체제별로 검토된 고정 package-manager recipe만 사용합니다.

현재 지원:

### macOS

Homebrew가 이미 설치되어 있을 때:

```bash
brew install ffmpeg
brew install fluid-synth
brew install lilypond
```

을 Setup Center에서 실행할 수 있습니다.

### Windows

winget이 있을 때 FFmpeg를 다음 고정 package ID로 설치할 수 있습니다.

```powershell
winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
```

다른 구성요소는 package ID/배포 경로를 충분히 고정할 수 있을 때만 자동 설치 대상으로 추가합니다.

### Linux

배포판마다 package manager와 package version이 크게 다르므로 현재 자동 관리자 설치를 강제하지 않습니다. 공식 다운로드 또는 사용 중인 배포판 package manager를 사용합니다.

## 공식 다운로드 fallback

자동 설치를 지원하지 않는 항목은 Setup Center에서 공식 배포 페이지를 제공합니다.

- LilyPond: `https://lilypond.org/download.html`
- Audiveris: `https://audiveris.github.io/audiveris/`
- FFmpeg: `https://ffmpeg.org/download.html`
- FluidSynth: `https://www.fluidsynth.org/download/`
- Hugging Face token: `https://huggingface.co/settings/tokens`

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

Setup Center 이후 남은 설치 UX 작업은 다음 순서가 적절합니다.

1. Windows/macOS signed installer 검증
2. 앱 번들에 포함할 수 있는 외부 runtime의 라이선스 검토
3. MuScriptor/MT3 모델 다운로드 진행률과 디스크 요구량 표시
4. Hugging Face 인증을 앱 내부 UX로 더 단순화
5. 설치 완료 후 sample score smoke test
6. 앱 업데이트와 DB/runtime migration 검증

외부 GPL/AGPL binary를 installer에 직접 번들하기 전에는 해당 배포 의무를 별도로 검토합니다.
