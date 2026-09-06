# AudioScoreTool 제3자 모델·라이선스 점검

이 문서는 **법률 자문이 아니라 제품 배포를 위한 기술적 provenance 체크리스트**입니다. 실제 유료 배포 직전에는 고정된 버전·모델 revision을 기준으로 다시 검토해야 합니다.

## 1. 기본 채보 엔진: YourMT3+ via MT3-Infer

### MT3-Infer

- 프로젝트: `openmirlab/mt3-infer`
- PyPI: `mt3-infer`
- AudioScoreTool 기준 검토 버전: **0.2.0**
- 프로젝트 라이선스: **MIT**
- 용도: MT3 계열 모델의 inference wrapper / checkpoint 관리 / CLI

MT3-Infer는 모델 weights를 패키지에 포함하지 않고 첫 사용 시 upstream에서 다운로드하는 구조입니다.

### YourMT3+

- 모델: YourMT3+ `YPTF.MoE+Multi (noPS)` 계열
- upstream checkpoint 저장소: `mimbres/YourMT3`
- Hugging Face model metadata: **Apache-2.0**
- 용도: multi-instrument / multi-track automatic music transcription

AudioScoreTool은 checkpoint를 자체 배포 파일에 복사해 넣지 않고 MT3-Infer의 upstream download/cache 경로를 사용합니다.

### 배포 전 확인

- [ ] 사용할 `mt3-infer` 버전을 고정
- [ ] `mt3-infer` LICENSE / external integration provenance 재확인
- [ ] YourMT3+ checkpoint repository의 license metadata가 여전히 Apache-2.0인지 확인
- [ ] 사용할 checkpoint revision/파일을 기록
- [ ] THIRD_PARTY_NOTICES에 저작권/라이선스 고지 반영
- [ ] checkpoint를 직접 재배포할 경우에는 별도의 법률 검토 수행

## 2. MuScriptor

- 소스 코드와 공개 model weights의 조건이 동일하지 않음
- 공개 weights는 비상업 조건이 포함된 라이선스로 제공됨
- AudioScoreTool에서는 **상용 기본 엔진으로 사용하지 않음**
- 호환성/연구/비교용 provider로만 유지

## 3. AudioScore Native

- AudioScoreTool 자체 R&D 경로
- 목표: project-owned checkpoint
- 일반 앱 사용에는 필요하지 않음
- 학습 manifest는 다음 라이선스만 자동 허용:
  - CC-BY-4.0
  - CC0-1.0
  - MIT
  - Apache-2.0
  - project-owned
- 비상업 라이선스가 들어오면 training 시작 전 거부

데이터셋의 표기 라이선스가 허용 목록에 들어간다는 사실만으로 모든 음원 저작권·실연권·데이터베이스권 문제가 자동 해결되는 것은 아닙니다. 실제 자체 모델 학습 전에는 dataset별 provenance를 별도로 검토해야 합니다.

## 4. Basic Pitch

- 프로젝트: Spotify `basic-pitch`
- 라이선스: Apache-2.0
- 모델 runtime 파일을 프로젝트가 함께 제공
- 장점: 작고 빠르며 instrument-agnostic polyphonic note transcription 지원
- 한계: 공식 문서에서도 **한 번에 한 악기**에서 가장 잘 동작한다고 설명함

따라서 현재 AudioScoreTool의 다중 악기 full-mix 기본 엔진으로는 YourMT3+가 더 적합하고, Basic Pitch는 향후 stem별 보조/fallback 엔진 후보입니다.

## 5. Demucs

- 코드: MIT
- 사용 목적: 현재 가사 인식 품질을 위한 vocal separation
- 주의: upstream에는 pretrained model weights의 라이선스 범위를 묻는 미해결 이슈가 존재함

AudioScoreTool은 Demucs를 **악기별 채보의 핵심 엔진으로 사용하지 않으며**, 가사 인식 보조 경로에만 사용합니다. 상용 배포에서 pretrained Demucs weights를 직접 번들하려면 별도 검토가 필요합니다. 필요하면 가사 분리 없이 WhisperX를 실행하는 fallback을 유지/추가하는 것이 더 안전합니다.

## 6. WhisperX

- 프로젝트: `m-bain/whisperX`
- 코드 라이선스: BSD-2-Clause
- 역할: word-level lyric timing

실제 ASR 실행 과정에서 다운로드되는 Whisper/faster-whisper/align model 등 개별 weights의 조건은 별도 구성요소로 확인해야 합니다.

## 7. OpenSheetMusicDisplay

- 라이선스: BSD-3-Clause
- 역할: 데스크탑 앱의 MusicXML 미리보기

## 8. MuseScore Studio

- 라이선스: GPL-3.0
- AudioScoreTool에서는 외부 실행 프로그램으로 호출
- 역할: MIDI ↔ MusicXML 변환 및 PDF 렌더링

현재 패키지는 MuseScore 바이너리를 AudioScoreTool에 정적으로 링크하거나 코드에 포함하지 않습니다. MuseScore 자체를 installer에 번들하는 배포 전략으로 바꿀 경우 GPL 의무를 별도로 검토해야 합니다.

## 권장 상용 구성

```text
AudioScoreTool
    ↓
YourMT3+ via MT3-Infer
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
