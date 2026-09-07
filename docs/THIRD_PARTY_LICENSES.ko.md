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

`usage_mode`는 법률 판단을 대신하는 장치가 아니라, 명백한 비상업 weights가 상용 경로에 실수로 들어가는 것을 막는 제품 안전장치입니다.

## 2. MuScriptor

- 소스 코드: MIT
- 공개 model weights: CC BY-NC 4.0
- 개인/비상업 기본 모델: `large`

```text
personal   → 사용 허용
commercial → 사용 차단
```

## 3. MT3-Infer / YourMT3+ / MR-MT3

### MT3-Infer

- AudioScoreTool 고정 버전: `0.2.0`
- wrapper: MIT
- model/checkpoint provenance는 wrapper와 분리해서 확인

### YourMT3+

- Hugging Face checkpoint metadata: Apache-2.0 표기
- `mt3-infer` vendored implementation: Apache-2.0 표기
- 공식 GitHub repository: GPL-3.0 표시

따라서 정확도 우선 상용 후보로는 유지하지만 실제 배포 source/checkpoint revision을 고정한 후 재검토해야 합니다.

### MR-MT3

- 원 구현/공개 checkpoint: MIT 표기
- YourMT3+보다 정확도가 낮을 수 있으나 provenance가 상대적으로 단순한 fallback

## 4. MIROS

2025 AMT Challenge winner 계열 후보입니다. provider에 포함하기 전 repository/checkpoint/encoder license와 재현 가능한 inference artifact를 고정해야 합니다.

## 5. AudioScore Native

- project-owned checkpoint 목표
- 일반 사용에는 필요 없음
- training manifest는 CC-BY-4.0 / CC0-1.0 / MIT / Apache-2.0 / project-owned만 자동 허용

데이터셋 표기만으로 음원 저작권·실연권·데이터베이스권이 해결되는 것은 아니므로 실제 학습 전 별도 provenance 검토가 필요합니다.

## 6. music21

- 라이선스: BSD 3-Clause
- 역할: MIDI ↔ MusicXML 변환
- v0.8부터 기본 Python dependency
- MuseScore 없이 MT3 계열 MIDI를 MusicXML로 변환하고 최종 MusicXML을 MIDI로 export하는 경로에 사용

MIDI는 표기 정보를 완전히 보존하는 형식이 아니므로 실제 AMT 결과에 대해 MuseScore 변환과의 notation fidelity를 Golden Set으로 비교하는 것이 좋습니다.

## 7. LilyPond / musicxml2ly

- 라이선스: GNU GPL
- 역할: MusicXML → LilyPond → PDF engraving
- AudioScoreTool에서는 별도 설치된 외부 실행 프로그램으로 호출
- installer에 직접 번들하는 경우 GPL 배포 의무를 별도로 검토

`musicxml2ly`는 MusicXML의 notes/articulations/score structure/lyrics 등을 변환하지만 모든 MusicXML 기능을 완벽하게 지원하는 것은 아닙니다. 따라서 PDF fidelity가 중요한 악보에서는 결과 검증이 필요합니다.

## 8. Audiveris

- 라이선스: GNU Affero GPL v3
- 역할: PDF/이미지 악보 OMR → MusicXML
- AudioScoreTool에서는 별도 설치된 외부 CLI로 호출
- 현재 Audiveris source/library를 Python 프로세스에 링크하지 않음

상용 installer에 Audiveris binary를 번들하거나 수정 버전을 배포한다면 AGPL 의무를 배포 방식 기준으로 별도 검토해야 합니다.

## 9. Basic Pitch

- Apache-2.0
- full-mix multi-instrument 기본 엔진보다는 stem별 보조/fallback 후보

## 10. Demucs

- 코드: MIT
- 역할: 가사 인식 품질을 위한 vocal separation
- pretrained weights 조건은 코드와 별도 확인 필요

## 11. WhisperX

- 코드: BSD-2-Clause
- 역할: word-level lyric timing
- Whisper/faster-whisper/alignment model weights는 실제 구성별 확인 필요

## 12. OpenSheetMusicDisplay

- BSD-3-Clause
- MusicXML 앱 내 미리보기

## 13. MuseScore Studio

- GPL-3.0
- **v0.8부터 필수 dependency가 아니라 선택적 compatibility fallback**
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
AudioScoreTool
```

### 상용 후보

```text
YourMT3+ via MT3-Infer
      ↓
music21 MIDI→MusicXML
      ↓
AudioScoreTool
```

YourMT3+는 상용 배포 전 provenance 검토가 필요합니다.

### 악보 이미지/PDF

```text
Audiveris (external)
      ↓
MusicXML
      ↓
AudioScoreTool validation/edit
```

### PDF 출력

```text
LilyPond/musicxml2ly (external)  ← 기본 대안
MuseScore (external)             ← 선택적 fallback
```
