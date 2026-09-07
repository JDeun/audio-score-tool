# AudioScoreTool 제3자 모델·라이선스 점검

이 문서는 **법률 자문이 아니라 제품 배포를 위한 기술적 provenance 체크리스트**입니다. 실제 유료 배포 직전에는 고정된 버전·모델 revision을 기준으로 다시 검토해야 합니다.

## 1. 사용 모드

v0.8부터 엔진 선택에 `usage_mode`를 둡니다.

### `personal`

- 개인 / 비상업 사용
- 정확도를 최우선
- MuScriptor-large 사용 허용
- 공개 weights의 CC BY-NC 4.0 조건을 사용자가 수락한 상태를 전제로 함

### `commercial`

- 유료 제품 / 상업적 서비스 / 상업 배포를 위한 모드
- MuScriptor 공개 weights를 API와 UI에서 차단
- MT3-Infer 계열 또는 project-owned Native만 선택 가능

`usage_mode`는 라이선스 판단을 자동으로 대신하는 법률 장치가 아니라, **명백한 비상업 weights가 상용 경로에 실수로 들어가는 것을 막는 제품 안전장치**입니다.

---

## 2. MuScriptor

- 프로젝트: `muscriptor/muscriptor`
- 소스 코드: MIT
- 공개 Hugging Face model weights: **CC BY-NC 4.0**
- AudioScoreTool 개인/비상업 기본 모델: `large`

따라서:

```text
personal   → 사용 허용
commercial → 사용 차단
```

상용 모드에서 `muscriptor` provider를 API로 직접 지정해도 실행 전에 거부합니다.

## 3. MT3-Infer

- 프로젝트: `openmirlab/mt3-infer`
- AudioScoreTool 고정 버전: `0.2.0`
- wrapper 프로젝트: MIT
- 역할: MR-MT3 / YourMT3 계열 inference, checkpoint 관리, CLI

MT3-Infer는 wheel 자체에 모든 weights를 포함시키는 대신 선택한 모델을 별도로 가져오는 구조이므로 **wrapper 코드 라이선스와 실제 model/checkpoint provenance를 분리해서 확인**해야 합니다.

## 4. YourMT3+

AudioScoreTool은 MT3 계열 중 정확도 우선 옵션으로 `yourmt3`를 사용합니다.

확인된 표기는 다음처럼 나뉩니다.

- Hugging Face `mimbres/YourMT3` checkpoint metadata: Apache-2.0
- `mt3-infer`가 vendoring한 YourMT3 implementation: Apache-2.0 표기
- 공식 GitHub `mimbres/YourMT3`: GPL-3.0 repository license 표시

따라서 개인 사용에는 품질 우선 모델로 적극 사용할 수 있지만, 상용 배포에서는 **어떤 source snapshot과 checkpoint를 실제 제품이 실행하는지 고정한 뒤 provenance를 다시 검토해야 합니다.**

AudioScoreTool은 이 상태를 `commercial_candidate`로 표시하고, 완전히 permissive하다고 단정하지 않습니다.

### 배포 전 체크리스트

- [ ] `mt3-infer` 최종 버전/revision 고정
- [ ] vendored YourMT3 source의 LICENSE 확인
- [ ] checkpoint repository revision/license metadata 고정
- [ ] checkpoint SHA-256 기록
- [ ] 공식 GPL repository 코드가 실제 binary/wheel에 섞여 들어오는지 확인
- [ ] THIRD_PARTY_NOTICES 작성

## 5. MR-MT3

- 원 구현: `gudgud96/MR-MT3`
- 공개 checkpoint: `gudgud1014/MR-MT3`
- 원 구현/공개 checkpoint: MIT 표기

YourMT3+보다 정확도가 낮을 수 있지만 현재 후보 중 **상용 provenance가 상대적으로 단순한 fallback**입니다.

## 6. MIROS

2025 AMT Challenge winner로 공개 저장소 `amt-os/ai4m-miros`가 존재하며 YourMT3+ framework를 확장한 구조입니다.

그러나 AudioScoreTool 기본 provider에 포함하기 전에는 다음을 먼저 고정해야 합니다.

- explicit repository license
- pretrained encoder/weights license
- inference artifact 배포 조건
- checkpoint download/reproduction 방법

단순히 challenge에서 가장 높은 F1을 기록했다는 이유만으로 제품에 포함하지 않습니다.

## 7. AudioScore Native

- AudioScoreTool 자체 R&D 경로
- 목표: project-owned checkpoint
- 일반 앱 사용에는 필요하지 않음
- 학습 manifest 허용 목록:
  - CC-BY-4.0
  - CC0-1.0
  - MIT
  - Apache-2.0
  - project-owned
- 비상업 라이선스 데이터가 들어오면 training 전에 거부

데이터셋 표기만으로 음원 저작권·실연권·데이터베이스권 문제가 자동 해결되는 것은 아니므로 자체 모델 학습 전 dataset provenance를 별도 검토해야 합니다.

## 8. Basic Pitch

- Spotify `basic-pitch`
- Apache-2.0
- 작고 빠른 instrument-agnostic transcription
- full-mix multi-instrument 기본 엔진보다는 stem별 보조/fallback에 가까움

## 9. Demucs

- 코드: MIT
- 현재 역할: 가사 인식 품질을 위한 vocal separation
- pretrained weights 조건은 코드와 별도로 확인 필요

## 10. WhisperX

- 코드: BSD-2-Clause
- 역할: word-level lyric timing
- Whisper/faster-whisper/alignment model weights는 실제 구성별 확인 필요

## 11. OpenSheetMusicDisplay

- BSD-3-Clause
- MusicXML 앱 내 미리보기

## 12. MuseScore Studio

- GPL-3.0
- AudioScoreTool에서는 외부 실행 프로그램으로 호출
- 현재 installer에 MuseScore 자체를 번들하지 않음

MuseScore binary를 직접 포함하는 전략으로 변경하면 GPL 의무를 별도 검토해야 합니다.

---

## 현재 권장 구성

### 개인 / 비상업

```text
MuScriptor large
      ↓
canonical MusicXML
      ↓
AudioScoreTool edit / validation / export
```

### 상용 후보

```text
YourMT3+ via MT3-Infer
      ↓
MusicXML
      ↓
AudioScoreTool
```

단, YourMT3+는 상용 배포 전 provenance 검토가 필요합니다.

### 상용 provenance 단순성 우선 fallback

```text
MR-MT3 via MT3-Infer
```
