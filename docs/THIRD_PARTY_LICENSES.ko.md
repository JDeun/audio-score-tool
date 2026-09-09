# AudioScoreTool 제3자 모델·라이선스 점검

이 문서는 **법률 자문이 아니라 제품 배포를 위한 기술적 provenance 체크리스트**입니다. 실제 유료/공식 배포 직전에는 고정된 package version, binary build flags, model revision을 기준으로 다시 검토해야 합니다.

## 1. 배포 원칙

AudioScoreTool 자체 코드는 Apache-2.0입니다. 그러나 bundled/managed component는 각자의 라이선스를 유지합니다.

일반 사용자에게 별도 프로그램 설치를 요구하지 않는다는 제품 원칙과, 제3자 binary를 합법적으로 재배포할 수 있는지는 별개의 문제입니다. 따라서 component별로 다음 중 하나를 선택합니다.

1. installer/sidecar에 직접 포함
2. 앱이 공식 upstream artifact를 별도로 다운로드·검증·관리
3. 라이선스/배포 조건이 맞지 않으면 기능을 optional/unavailable로 유지하거나 다른 구현으로 대체

세부 runtime 분류는 [`DEPENDENCIES.ko.md`](DEPENDENCIES.ko.md)를 참조하십시오.

## 2. 사용 모드와 모델 라이선스

### `personal`

- 개인 / 비상업 사용
- 품질 우선 provider 허용
- MuScriptor 공개 weights의 CC BY-NC 4.0 조건을 수락한 경우 사용 가능

### `commercial`

- 상업적 제품/서비스/배포 경로
- MuScriptor 공개 weights 차단
- 상업 사용이 허용되는 checkpoint/provider만 선택

`usage_mode`는 법률 판단을 대신하지 않으며 명백한 비상업 weights가 상용 경로에 실수로 들어가는 것을 막는 기술적 안전장치입니다.

## 3. MuScriptor

- 소스 코드: MIT
- 공개 model weights: CC BY-NC 4.0
- personal/non-commercial에서만 공개 weights 사용
- commercial에서는 차단

## 4. MT3-Infer / YourMT3+ / MR-MT3

### MT3-Infer

- AudioScoreTool 고정 버전: `0.2.0`
- wrapper license와 checkpoint license를 분리해서 확인
- stable desktop에서는 `uvx` 수동/자동 실행이 아니라 app-managed runtime artifact가 필요

### YourMT3+

checkpoint/implementation 출처별 license metadata가 동일하지 않을 수 있으므로 정확한 배포 revision을 고정한 뒤 재검토합니다. 단순 모델명만으로 상용 재배포 가능성을 확정하지 않습니다.

### MR-MT3

fallback 후보입니다. 실제 포함 시 사용한 repository/checkpoint revision과 license file을 release provenance에 기록합니다.

## 5. AudioScore Native

- project-owned checkpoint 목표
- training manifest는 명시적으로 허용된 데이터 license만 자동 승인
- dataset license와 원음 저작권/실연권/데이터베이스권은 별개로 검토

## 6. music21

- 역할: MIDI ↔ MusicXML
- 기본 Python dependency
- packaged sidecar에 포함
- BSD 계열 license notice를 실제 고정 version 기준으로 release artifact에서 보존

## 7. Verovio

- 역할: MusicXML engraving → page별 SVG
- Python binding을 packaged sidecar에 포함
- LGPLv3 계열
- upstream은 desktop/commercial embedding 자체를 허용하지만 LGPL 조건과 attribution/source 제공 의무를 지켜야 함
- 가능하면 upstream wheel을 수정하지 않고 사용하고, 배포 시 exact version과 notice를 기록

PDF renderer의 notation engine은 Verovio이며 MuseScore/LilyPond fallback을 사용하지 않습니다.

## 8. fpdf2

- 역할: Verovio SVG page를 vector PDF page로 변환하고 multi-page PDF를 생성
- Python dependency로 sidecar에 포함
- LGPL-3.0 계열
- exact version/license notice를 release provenance에 기록

```text
MusicXML → Verovio SVG → fpdf2 PDF
```

## 9. OpenSheetMusicDisplay

- BSD-3-Clause
- frontend MusicXML preview/edit visualization
- JavaScript bundle에 포함

OSMD와 Verovio는 역할을 분리합니다. OSMD는 interactive desktop preview, Verovio는 deterministic backend PDF export를 담당합니다.

## 10. Audiveris

- 역할: PDF/이미지 OMR → MusicXML
- AGPL-3.0 계열
- 현재 integration은 executable boundary
- 최신 배포판은 자체 JRE를 포함할 수 있지만, AudioScoreTool이 이를 재배포/자동 관리할 경우 AGPL 및 포함 dependency 의무를 실제 artifact 기준으로 검토해야 함

따라서 OMR은 core installer dependency가 아닙니다. 공식 stable에서 OMR을 기본 제공하려면:

- Audiveris managed component의 배포 의무를 충족하거나
- 재배포 조건이 더 단순한 embedded OMR backend로 교체

중 하나를 결정합니다.

## 11. FFmpeg / ffprobe

- 역할: media decode/normalize, YouTube support, optional audio evidence
- FFmpeg 기본 코드는 주로 LGPL 2.1+이나 build option/external library에 따라 GPL 또는 nonfree가 될 수 있음
- `--enable-nonfree` 결과물은 재배포 불가 조건이 발생할 수 있으므로 사용 금지
- AudioScoreTool이 managed binary를 제공할 경우 **binary 자체의 configure flags와 license inventory를 고정**해야 함

단순히 “FFmpeg”라는 이름만 보고 재배포 가능 여부를 판단하지 않습니다.

## 12. yt-dlp / YouTube runtime

- 역할: YouTube metadata/audio ingest
- Python package와 standalone binary의 포함물/license profile이 다를 수 있으므로 실제 delivery artifact 기준으로 검토
- 현재 YouTube 지원은 yt-dlp 외에 FFmpeg/ffprobe 및 JavaScript challenge runtime/ejs가 필요할 수 있음

stable 지원에서는 이 전체를 하나의 app-managed component stack으로 취급합니다. 사용자가 Python/Node/Deno/FFmpeg를 각각 설치하게 하지 않습니다.

## 13. Demucs

- 역할: vocal/source separation
- code와 pretrained weights의 조건을 분리 확인
- inference runtime가 크므로 managed-model-runtime 후보

## 14. WhisperX

- 역할: lyric recognition/alignment
- code, Whisper/faster-whisper, alignment model의 license/provenance를 구성별로 확인
- managed-model-runtime 후보

## 15. FluidSynth / SoundFont

- 역할: optional MIDI resynthesis validation
- FluidSynth binary/library license와 실제 bundled build를 확인
- SoundFont는 별도 저작물일 수 있으므로 자동으로 임의 GM SoundFont를 번들하지 않음
- 사용자가 자신의 SoundFont를 선택하는 경로는 허용하되 핵심 workflow에는 필수가 아님

## 16. Chromaprint / AcoustID

- 역할: optional acoustic fingerprint/source identification
- Chromaprint/fpcalc binary와 AcoustID service terms를 별도로 확인
- service commercial entitlement와 local binary license를 혼동하지 않음

## 17. LLM / Vision providers

- 선택적 external service
- 기본 OFF
- 핵심 ingest/edit/export에 필요하지 않음
- provider terms, data transfer, API key handling은 별도 보안/서비스 정책 적용

## 현재 권장 배포 경계

### installer/sidecar에 포함

```text
Tauri + frontend bundle
Python FastAPI sidecar
music21
Verovio
fpdf2
```

### app-managed component/model

```text
AMT runtime + weights
Demucs / WhisperX
YouTube stack
FFmpeg/ffprobe
OMR backend
FluidSynth
Chromaprint
```

### optional external service/account

```text
Hugging Face gated-model authentication
LLM/Vision API
MusicBrainz/AcoustID service
```

### 제거된 runtime dependency

```text
MuseScore
LilyPond
musicxml2ly
system Python/Node/Rust/uv/pip
```

각 stable release는 설치 artifact에 실제 포함된 구성요소를 다시 inventory하고 해당 version/license/source 정보를 함께 기록해야 합니다.
