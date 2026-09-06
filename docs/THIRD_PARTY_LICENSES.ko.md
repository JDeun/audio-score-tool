# AudioScoreTool 제3자 모델·라이선스 점검

이 문서는 **법률 자문이 아니라 제품 배포를 위한 기술적 provenance 체크리스트**입니다. 실제 유료 배포 직전에는 고정된 버전·모델 revision을 기준으로 다시 검토해야 합니다.

## 1. 기본 채보 엔진: MR-MT3 via MT3-Infer

### MT3-Infer

- 프로젝트: `openmirlab/mt3-infer`
- PyPI: `mt3-infer`
- AudioScoreTool 기준 고정 버전: **0.2.0**
- 프로젝트 라이선스: **MIT**
- 역할: MR-MT3 / YourMT3 등 MT3 계열 모델의 inference wrapper, checkpoint 관리, CLI

MT3-Infer는 model weights를 wheel에 포함하지 않고 첫 사용 시 upstream에서 다운로드하는 구조입니다.

### MR-MT3

- 원 구현: `gudgud96/MR-MT3`
- 모델: Memory Retaining Multi-Track Music Transcription
- 용도: multi-instrument / multi-track automatic music transcription
- 원 구현 라이선스: **MIT 표기**
- AudioScoreTool이 기본으로 사용하는 공개 checkpoint: `gudgud1014/MR-MT3`
- Hugging Face model metadata: **MIT 표기**

현재 AudioScoreTool은 이 조합을 **상업 기본 후보**로 사용합니다. checkpoint를 installer 안에 복사해 넣지 않고 MT3-Infer가 upstream에서 로컬 캐시로 가져오게 합니다.

### 배포 전 확인

- [ ] `mt3-infer==0.2.0` 또는 최종 선택 버전을 고정
- [ ] MT3-Infer LICENSE 및 `external_integrations` provenance 재확인
- [ ] MR-MT3 원 저장소 라이선스가 MIT인지 재확인
- [ ] 사용할 MR-MT3 checkpoint revision의 Hugging Face license metadata가 MIT인지 재확인
- [ ] checkpoint revision / SHA-256을 THIRD_PARTY_NOTICES에 기록
- [ ] checkpoint를 제품 installer에 직접 재배포할 경우 별도 배포 조건 검토

## 2. YourMT3+

- `mt3-infer`에서 선택 가능한 고품질 다중 악기 backend
- checkpoint Hugging Face 저장소 `mimbres/YourMT3`는 Apache-2.0으로 표기
- 반면 공식 GitHub source repository는 GPL-3.0으로 표시되는 시점이 있어 **source/checkpoint provenance 표기가 일관되지 않음**
- 따라서 품질 비교·실험 옵션으로는 유지하지만 상용 기본값으로 고정하지 않음

유료 제품에서 YourMT3+를 기본 엔진으로 바꾸기 전에는 사용할 source snapshot과 checkpoint를 기준으로 별도 라이선스 검토가 필요합니다.

## 3. MuScriptor

- 소스 코드와 공개 model weights의 조건이 동일하지 않음
- 공개 weights에는 비상업 조건이 포함됨
- AudioScoreTool에서는 **상용 기본 엔진으로 사용하지 않음**
- 호환성 / 연구 / 비교용 provider로만 유지

## 4. AudioScore Native

- AudioScoreTool 자체 R&D 경로
- 목표: project-owned checkpoint
- 일반 앱 사용에는 필요하지 않음
- 학습 manifest는 다음 라이선스만 자동 허용:
  - CC-BY-4.0
  - CC0-1.0
  - MIT
  - Apache-2.0
  - project-owned
- 비상업 라이선스 데이터가 들어오면 training 시작 전 거부

데이터셋의 표기 라이선스가 allowlist에 있다는 사실만으로 모든 음원 저작권·실연권·데이터베이스권 문제가 자동 해결되는 것은 아닙니다. 실제 자체 모델 학습 전에는 dataset별 provenance를 별도로 검토해야 합니다.

## 5. Basic Pitch

- 프로젝트: Spotify `basic-pitch`
- 라이선스: Apache-2.0
- 장점: 작고 빠르며 instrument-agnostic polyphonic note transcription 지원
- 한계: 공식 문서 기준 한 번에 한 악기에서 가장 잘 동작함

따라서 다중 악기 full-mix 기본 엔진보다는 stem별 보조 / fallback 후보에 가깝습니다.

## 6. Demucs

- 코드: MIT
- 역할: 현재 가사 인식 품질을 위한 vocal separation
- 주의: pretrained model weights의 라이선스 범위는 코드 라이선스와 별도 확인 필요

AudioScoreTool은 Demucs를 악기별 채보 핵심 엔진으로 사용하지 않고 가사 인식 보조 경로에만 사용합니다. 상용 installer에 weights를 직접 번들하려면 별도 검토가 필요합니다.

## 7. WhisperX

- 프로젝트: `m-bain/whisperX`
- 코드 라이선스: BSD-2-Clause
- 역할: word-level lyric timing

실제 실행 중 내려받는 Whisper / faster-whisper / align model 등의 weights 조건은 개별 구성요소로 확인해야 합니다.

## 8. OpenSheetMusicDisplay

- 라이선스: BSD-3-Clause
- 역할: 데스크탑 앱의 MusicXML 미리보기

## 9. MuseScore Studio

- 라이선스: GPL-3.0
- AudioScoreTool에서는 외부 실행 프로그램으로 호출
- 역할: MIDI → MusicXML 변환 및 PDF 렌더링

현재 패키지는 MuseScore 코드를 정적으로 링크하거나 바이너리를 제품에 포함하지 않습니다. MuseScore 자체를 installer에 번들하는 전략으로 바꾸면 GPL 의무를 별도로 검토해야 합니다.

## 권장 상용 구성

```text
AudioScoreTool
    ↓
MR-MT3 via MT3-Infer
    ↓
multi-track MIDI
    ↓
MuseScore (external process)
    ↓
MusicXML
    ↓
자동 코드 + 가사 + 편집 + 조판
```

이 구성이 현재 기준으로 **처음부터 자체 AMT 모델을 학습하지 않으면서 MuScriptor의 비상업 weights를 기본 경로에서 제거하는 가장 현실적인 구조**입니다.
