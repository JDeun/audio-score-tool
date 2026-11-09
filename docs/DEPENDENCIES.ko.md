# AudioScoreTool 의존성 및 독립 실행 정책

## Python 지원 정책 (2026-11-05)

- 소스 기반 Python backend의 지원 최소 버전은 **Python 3.11**입니다. 개발자용 권장 버전은 기존 README의 **3.12+**를 유지합니다.
- Python 3.10은 2026-10-01 EOL이므로 보안 업데이트가 종료되었고, Pillow 13 및 filelock 4.2.x의 안전한 버전을 모두 충족할 수 없어 지원 대상에서 제외합니다. 변경의 추적 이슈: #50.
- 일반 데스크톱 사용자는 Python을 설치할 필요가 없습니다. PyInstaller sidecar를 앱에 포함하는 배포 계약은 변경하지 않습니다. 이전 Python 3.10 환경에서 source checkout을 사용했다면 3.11+로 전환해야 합니다.
- 의존성 취약점 검사는 런타임과 릴리스 빌드 도구를 모두 포함하며, 결과를 보안 예외로 무시하지 않습니다.

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

### MuScriptor 비상업 채보 실행 경로 (#55)

모델 관리자가 사용자의 Hugging Face 라이선스 수락·인증 후 다운로드한 동일 버전의 `model.safetensors`와 `config.json`이 HF cache에 모두 있어야 MuScriptor를 실행합니다. 앱은 해당 **local snapshot 경로**를 `--model`에 전달하므로, 추론 subprocess가 사용자 세션 token을 공유하거나 모델을 임의로 다시 다운로드할 필요가 없습니다. inference 시에는 HF offline 설정을 강제합니다. 캐시 파일/구조가 불완전하거나 model config가 선택한 small/medium/large와 불일치하면 unavailable로 표시합니다.

MuScriptor CLI의 `--format sheets`는 외부 MuseScore 4를 요구하므로 호출하지 않습니다. 대신 `--format midi --output <app job>/score.mid`로 추론한 후 앱에 내장된 `music21`로 `score.musicxml`을 생성하고, 사용자의 명시적 최종 출판 시 Verovio/fpdf2로 PDF를 만듭니다. MIDI에 note-on 이벤트가 없거나 파일 형식이 손상된 경우 작업을 성공으로 처리하지 않습니다.

**검증 범위:** 위 연결은 실제 런타임/권한/성능의 출시 검증이 아니라 코드와 합성 MIDI에 대한 회귀 계약입니다. 모델 SHA-256·고정 revision·상용 재배포 승인은 별도 증빙이 필요하고, 공개 가중치는 CC BY-NC 4.0으로 상용 모드에서 차단합니다.

## 개발자 override

source checkout과 integration debugging을 위해 `AST_*_CMD` 환경변수 일부를 유지할 수 있습니다. 이것은 다음 목적에 한정합니다.

- 특정 upstream executable 실험
- CI/integration test fixture
- app-managed component 구현 이전의 개발 검증

정식 installer acceptance에서는 override가 없는 깨끗한 환경을 사용합니다.

패키지 모드(`AST_PACKAGED=1`)의 `GET /api/health`, `GET /api/setup`, `GET /api/engines`는 `packaged_runtime: true`를 반환합니다. 이 모드에서 UI는 개발용 실행 파일 경로 입력을 숨기고 Setup Center의 managed component 설치·검증·복구 상태를 안내합니다. `PUT /api/settings/tool-paths`를 직접 호출해도 HTTP 409로 거부하며, 이전에 저장된 개발 경로를 packaged runtime이 실행하지 않는 기존 정책은 유지합니다. 엔진 선택·모델 크기 설정은 계속 제공하되, 개발용 Native 실행 명령은 배포 사용자에게 제공하지 않습니다.

### SheetSage2 선택 분석 어댑터 (연구 전용, #43)

SheetSage2 공개 체크포인트는 **CC BY-NC 4.0**이며 상용 모드에서 실행할 수 없습니다. 해당 기능은 현재 승인된 필수 배포 구성요소가 아니므로, 모델을 자동으로 설치하거나 제품 기본 채보 엔진으로 승격하지 않습니다.

개발자 PoC의 `AST_SHEETSAGE2_ADAPTER`는 원음과 새 이벤트 JSON 출력 경로를 인수로 받습니다. 이 실행은 공통 `run_command`를 통과합니다. 즉 `AST_PACKAGED=1`에서는 검증된 앱 관리형 실행파일이 아니면 실행이 거부되며, 시스템 PATH나 임의 Python 래퍼로 우회할 수 없습니다. 모델이 반환하는 `schema_version=1` JSON은 크기·시간축 및 `model=sheetsage2`를 검증한 후에만 기존 분석 파일을 원자적으로 갱신합니다. 이전 결과가 남아 있더라도 새 실행이 실패하면 성공으로 재사용하지 않습니다.

이는 **선택 분석기 실행 경계 강화**이지 신규 사용자 기능의 end-to-end 출시 승인이 아닙니다. checkpoint revision/hash, 별도 재배포 권리, clean-machine 성능, 오디오→Song 자동 보강 및 실측 KPI는 #43, #29에서 계속 추적합니다.

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
