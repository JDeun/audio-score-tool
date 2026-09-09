# 설치 및 첫 실행 설계

AudioScoreTool의 일반 사용자 설치 계약은 다음입니다.

> **새 PC에서 설치 파일 하나를 실행한 뒤, Python/Node/Rust나 별도 악보 프로그램을 설치하지 않고 핵심 악보 workflow를 사용할 수 있어야 합니다.**

## 현재 배포 상태

| 등급 | 용도 | 상태 |
|---|---|---|
| source/development | 개발·기여 | 사용 가능 |
| unsigned Desktop Packages | Windows/macOS/Linux QA | CI에서 생성 가능 |
| signed stable installer | 일반 사용자 공식 배포 | signing/acceptance 전 (#22) |

unsigned CI artifact는 QA용입니다. Windows Authenticode signing, macOS Developer ID notarization, updater acceptance가 끝나기 전에는 공식 stable 배포본으로 안내하지 않습니다. 운영 gate는 [Issue #22](https://github.com/JDeun/audio-score-tool/issues/22)입니다.

## 일반 사용자에게 요구하지 않는 것

- Python / Node.js / Rust 설치
- `pip`, `uv`, `uvx`, `npm`, `cargo` 사용
- Homebrew / winget으로 후설치
- PATH 수동 편집
- MuseScore 설치
- LilyPond / `musicxml2ly` 설치
- 개발용 가상환경 구성

Desktop package는 Tauri UI와 Python backend sidecar를 함께 제공합니다. 큰 모델이나 선택 기능의 runtime은 installer에 직접 포함하거나 앱이 자체 관리하는 component로 제공하는 것이 원칙입니다.

자세한 분류는 [`DEPENDENCIES.ko.md`](DEPENDENCIES.ko.md)를 참조하십시오.

## 핵심 내장 workflow

| 입력/기능 | 배포 계약 |
|---|---|
| MusicXML/XML/MXL import | 기본 앱 |
| MIDI import/export | sidecar 내장 music21 |
| 악보 미리보기/편집 | frontend bundle의 OSMD + 앱 editor |
| PDF/파트 PDF export | sidecar 내장 Verovio + fpdf2 |
| SQLite 곡/Revision 관리 | 기본 앱 |

PDF 생성 경로는 다음과 같습니다.

```text
Canonical MusicXML
        ↓
     Verovio
        ↓
 page별 vector SVG
        ↓
      fpdf2
        ↓
 multi-page vector PDF
```

MuseScore, LilyPond, `musicxml2ly`는 PDF fallback으로도 호출하지 않습니다.

## 모델/기능별 managed component

다음 기능은 크기·라이선스·업데이트 주기가 핵심 앱과 달라 별도 component가 될 수 있습니다. **별도 component라는 의미는 사용자가 시스템 package를 직접 설치한다는 뜻이 아닙니다.**

- AMT transcription engine + weights
- Demucs
- WhisperX/alignment model
- YouTube ingest stack (`yt-dlp`, 필요한 media/JS runtime)
- Audiveris + 필요한 Java runtime 또는 향후 대체 OMR backend
- FFmpeg/ffprobe
- FluidSynth
- Chromaprint/fpcalc

현재 packaged build에서 실제 관리형 delivery가 완성되지 않은 component는 `ready`로 과장하지 않습니다. stable release에서 해당 기능을 공식 지원하려면 앱이 설치·검증·업데이트·삭제 lifecycle을 소유해야 합니다.

## Setup Center 정책

Setup Center는 더 이상 Homebrew/winget 설치 도우미가 아닙니다. 역할은 다음과 같습니다.

1. 앱에 반드시 내장되어야 할 핵심 runtime 검증
2. app-managed model/component 준비 상태 표시
3. 라이선스상 별도 동의/인증이 필요한 모델의 상태 표시
4. 선택적 외부 서비스 상태 표시

핵심 component가 installer에서 누락되었다면 사용자의 PC 환경 문제가 아니라 **패키징 결함**으로 취급합니다.

## 기능별 readiness

### 핵심

```text
MusicXML/MIDI ingest → edit → validation → publication → MusicXML/MIDI/PDF export
```

이 경로는 별도 시스템 프로그램 없이 동작해야 합니다.

### 자동 채보

AMT engine/model이 필요합니다. 정식 데스크탑 UX에서는 `uvx`나 `pip install`을 사용자에게 요구하지 않고, 앱에 포함하거나 앱 데이터 영역에서 관리합니다.

MuScriptor 공개 weights는 CC BY-NC 4.0이므로 personal/non-commercial mode에서만 허용합니다. commercial mode에서는 비상업 weights가 자동 선택되지 않아야 합니다.

### YouTube

YouTube import는 선택 기능입니다. 현재 upstream 생태계는 `yt-dlp` 외에도 FFmpeg/ffprobe와 YouTube challenge 대응용 JS runtime/ejs가 필요할 수 있으므로, stable 지원 시 이 전체 stack을 하나의 app-managed component로 취급합니다.

### PDF/이미지 OMR

Audiveris 기반 OMR은 선택 기능입니다. 사용자가 Java/Audiveris를 시스템에 직접 설치해야 하는 상태를 최종 사용자 경험으로 간주하지 않습니다. stable 지원 시 필요한 runtime을 앱이 관리하거나 embedded OMR backend로 대체합니다.

### 가사/오디오 검증

WhisperX, Demucs, FFmpeg, FluidSynth, SoundFont 등은 관련 기능에만 영향을 줍니다. 이들의 부재가 MusicXML/MIDI/PDF 편집·출판 workflow를 차단해서는 안 됩니다.

## 계정/네트워크가 필요한 경우

설치 dependency와 계정/서비스 dependency를 구분합니다.

- gated Hugging Face model: 공식 라이선스 수락/인증이 필요할 수 있음
- LLM/Vision validator: 사용자가 명시적으로 켜는 선택적 API
- MusicBrainz/AcoustID: 선택적 source-identification 서비스

이 경우에도 별도 개발도구 설치는 요구하지 않습니다. token/API key 값 자체를 AudioScoreTool DB에 평문 저장하지 않는 기존 보안 원칙을 유지합니다.

## 개발자 설치

개발자만 다음 toolchain을 사용합니다.

```bash
git clone https://github.com/JDeun/audio-score-tool.git
cd audio-score-tool
uv sync --extra dev

cd desktop
npm ci
npm run desktop:dev
```

`.env.example`의 `AST_*_CMD` 값은 source/integration 개발용 override이며 일반 사용자 설치 절차가 아닙니다.

## stable installer acceptance

signing뿐 아니라 **독립 실행성**을 실제로 검증해야 합니다.

1. clean Windows/macOS 환경 사용
2. system Python/Node/Rust/uv/pip 없음
3. MuseScore/LilyPond 없음
4. Homebrew/winget 후설치 없음
5. install → launch 성공
6. MusicXML/MXL/MIDI import → edit → PDF/MIDI/MusicXML export 성공
7. part PDF export 성공
8. packaged sidecar에서 music21/Verovio/fpdf2 실제 실행 성공
9. 공식 지원하는 managed component 기능은 앱 안에서 준비 가능
10. update → relaunch 및 invalid updater signature rejection 성공

코드 signing/notarization과 updater credential 작업은 [#22](https://github.com/JDeun/audio-score-tool/issues/22)에서 추적합니다. dependency별 배포 방식과 라이선스는 [`DEPENDENCIES.ko.md`](DEPENDENCIES.ko.md), [`THIRD_PARTY_LICENSES.ko.md`](THIRD_PARTY_LICENSES.ko.md)를 함께 확인합니다.
