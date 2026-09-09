# AudioScoreTool 의존성 및 독립 실행 정책

이 문서는 AudioScoreTool 데스크탑 배포본이 어떤 구성요소를 **앱에 내장하고**, 어떤 구성요소를 **앱이 관리하며**, 어떤 기능을 **선택적 외부 서비스**로 취급하는지 정의합니다.

## 최상위 원칙

> **일반 사용자는 AudioScoreTool을 설치하기 위해 Python, Node.js, Rust, uv/pip, Homebrew/winget, MuseScore, LilyPond, Java 같은 개발도구나 별도 애플리케이션을 수동 설치하지 않는다.**

개발자가 source checkout에서 사용하는 CLI/환경변수는 일반 사용자 설치 계약이 아닙니다.

## 전달 방식

| 분류 | 의미 | 사용자 수동 시스템 설치 |
|---|---|---|
| `embedded` | installer/app bundle 또는 Python sidecar에 포함 | 없음 |
| `managed-model-runtime` | 큰 inference runtime/model을 앱 데이터 영역에서 앱이 내려받고 검증·관리 | 없음 |
| `managed-component` | 기능별 native/runtime 자산을 앱이 버전·checksum과 함께 관리 | 없음 |
| `account-credential` | 모델/서비스 라이선스상 사용자의 공식 계정 인증 필요 | 계정 인증만 필요 |
| `external-service` | 사용자가 명시적으로 켜는 네트워크 API | 로컬 프로그램 설치 없음 |

## 현재 dependency inventory

### 핵심 내장 구성요소

| 구성요소 | 역할 | 정책 |
|---|---|---|
| Tauri | desktop shell / installer / updater | app bundle |
| React + TypeScript + Vite output | desktop UI | app bundle |
| OpenSheetMusicDisplay | MusicXML 화면 렌더링 | frontend bundle |
| Python FastAPI backend | 로컬 API/오케스트레이션 | PyInstaller sidecar |
| SQLite | canonical song/revision state | Python runtime |
| music21 | MIDI ↔ MusicXML | Python sidecar dependency |
| Verovio | MusicXML engraving → SVG | Python sidecar dependency |
| fpdf2 | Verovio SVG page → vector PDF | Python sidecar dependency |

### 앱 관리형 구성요소

다음 항목은 기능/모델 크기나 라이선스 때문에 installer 본체에 모두 넣지 않을 수 있습니다. 그렇더라도 정식 사용자 flow에서 `pip install`, `uvx`, Homebrew, winget, Java 설치 등을 요구해서는 안 됩니다.

| 구성요소 | 역할 | 목표 delivery |
|---|---|---|
| AMT engine + weights | audio → symbolic score | managed-model-runtime |
| Demucs | vocal stem separation | managed-model-runtime/component |
| WhisperX + alignment model | lyric recognition/alignment | managed-model-runtime |
| yt-dlp stack | YouTube metadata/audio ingest | managed-component |
| FFmpeg/ffprobe | media decode/normalize, YouTube support, optional validation | managed-component |
| YouTube JS challenge runtime/ejs | current YouTube extraction support | managed-component |
| Audiveris + required Java runtime | PDF/image OMR | managed-component 또는 향후 embedded OMR 대체 |
| FluidSynth | optional MIDI resynthesis validation | managed-component |
| Chromaprint/fpcalc | optional acoustic fingerprint | managed-component |

`managed-*` 구현이 아직 완료되지 않은 기능은 stable release에서 **준비됨으로 과장하지 않습니다.** 해당 기능은 component가 실제로 설치·검증된 경우에만 ready가 됩니다.

## 선택적 외부 서비스

- LLM/Vision validation
- MusicBrainz/AcoustID 등 사용자가 선택한 metadata service
- Hugging Face 계정 인증이 필요한 gated model 접근

이들은 핵심 로컬 편집/출판 workflow를 차단하지 않습니다. API key/token 원문을 AudioScoreTool DB에 평문 저장하지 않는 기존 보안 정책을 유지합니다.

## 제거된 일반 사용자 의존성

다음은 runtime requirement 또는 fallback으로 사용하지 않습니다.

- MuseScore
- LilyPond
- `musicxml2ly`
- system Python
- Node.js
- Rust toolchain
- `pip` / `uv` / `uvx`
- Homebrew / winget

PDF는 `MusicXML → Verovio SVG → fpdf2 vector PDF` 경로로 앱 내부에서 생성합니다.

## 개발자 override

source checkout과 integration debugging을 위해 `AST_*_CMD` 환경변수 일부를 유지할 수 있습니다. 이것은 다음 목적에 한정합니다.

- 특정 upstream executable 실험
- CI/integration test fixture
- app-managed component 구현 이전의 개발 검증

정식 installer acceptance에서는 override가 없는 깨끗한 환경을 사용합니다.

## 배포 acceptance

stable release 후보는 깨끗한 Windows/macOS 환경에서 다음 조건을 만족해야 합니다.

1. system Python/Node/Rust/uv/pip 없음
2. MuseScore/LilyPond 없음
3. Homebrew/winget을 사용한 후설치 없음
4. MusicXML/MXL/MIDI import → edit → MusicXML/MIDI/PDF export 성공
5. PDF/파트 PDF가 embedded renderer로 생성됨
6. 설치본에 포함되어야 하는 Python modules가 packaged sidecar 안에서 실제 import/실행됨
7. managed component를 사용하는 기능은 앱 UI에서 설치/검증/삭제/업데이트가 가능하거나, 구현 전에는 명확히 unavailable로 표시됨
8. 선택 기능 실패가 무관한 핵심 workflow를 차단하지 않음

## 라이선스 원칙

의존성을 기술적으로 bundle할 수 있다는 사실과 재배포해도 된다는 사실은 다릅니다.

- binary/component를 bundle하거나 자동 다운로드하기 전에 정확한 version/revision/license/source를 기록합니다.
- FFmpeg는 실제 배포 build flags에 따라 LGPL/GPL/nonfree 조건이 달라질 수 있으므로 배포 artifact를 기준으로 확인합니다.
- Audiveris는 AGPL 계열 의무를 배포 방식 기준으로 별도 검토합니다.
- MuScriptor 공개 weights의 CC BY-NC 제한은 commercial mode에서 계속 차단합니다.
- Verovio/fpdf2처럼 LGPL 구성요소를 배포할 때도 해당 라이선스 notice/source 제공 의무를 release checklist에 반영합니다.

세부 provenance는 [`THIRD_PARTY_LICENSES.ko.md`](THIRD_PARTY_LICENSES.ko.md)를 참고하십시오.
