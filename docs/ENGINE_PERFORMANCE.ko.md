# 채보 엔진 성능과 선택 기준

> 공개 benchmark는 dataset, metric, instrument mapping, checkpoint가 다르므로 숫자를 가로로 단순 비교하면 안 됩니다. 이 문서는 제품 선택을 위한 상대적 특성을 정리합니다.

## 1. MR-MT3

AudioScoreTool의 기본값입니다.

MR-MT3는 MT3의 대표적인 문제인 **instrument leakage**를 줄이기 위해 이전 segment의 memory를 유지하는 구조를 추가합니다. 논문은 Slakh2100에서 onset F1 개선과 leakage 감소를 보고합니다.

MT3-Infer가 RTX 4090에서 측정한 inference benchmark에서는 MR-MT3가 약 **57× real-time**, checkpoint는 약 **176 MB**로 보고되어 현재 지원 후보 중 가장 빠른 편입니다.

### 제품 관점

- 강점: 속도, 작은 checkpoint, 악기 assignment 일관성, MIT 계열 배포 경로
- 약점: 절대 transcription accuracy만 보면 YourMT3+가 더 좋은 benchmark를 보이는 경우가 있음
- 권장: 기본 엔진 / 일반 사용자 / 상용 제품

## 2. YourMT3+

YourMT3+의 `YPTF.MoE+M` 계열은 Slakh2100에서 공개 leaderboard 기준 Onset F1 약 **84.56**, Multi F1 약 **74.84**로 보고되어 MT3 baseline보다 크게 개선된 결과를 보입니다.

MT3-Infer의 기본 YourMT3 checkpoint는 약 **536 MB**, RTX 4090 기준 약 **15× real-time** 수준으로 소개됩니다.

### 제품 관점

- 강점: 높은 다중 악기 transcription accuracy
- 약점: MR-MT3보다 느리고 checkpoint가 큼
- 권장: Quality 모드 / MR-MT3와 A/B 비교
- 배포: 실제 사용하는 checkpoint와 vendored code의 provenance를 출시 전 다시 확인

## 3. MuScriptor

MuScriptor 1.3B 공개 모델 카드의 자체 `D_Test` 372곡 평가에서는 YourMT3+ baseline 대비 큰 폭의 향상을 보고합니다.

| Model | Onset F1 | Frame F1 | Offset F1 | Drums F1 | Multi F1 |
|---|---:|---:|---:|---:|---:|
| YourMT3+ baseline | 32.5 | 45.5 | 17.8 | 41.4 | 21.9 |
| MuScriptor 1.3B | 60.4 | 72.4 | 48.6 | 49.6 | 47.8 |

이 숫자는 Slakh2100 leaderboard와 **동일한 평가 프로토콜이 아니므로** MR-MT3/YourMT3+의 다른 표와 직접 비교하면 안 됩니다.

### 제품 관점

- 강점: 최신 대형 모델, 실제 multi-instrument 혼합음원에서 높은 잠재 품질
- 약점: 1.3B 모델은 무겁고 latency/VRAM 부담이 큼
- 결정적 제약: 공개 weights가 **CC-BY-NC**로 명시되어 상용 제품 기본 엔진으로 사용할 수 없음
- 권장: 연구/내부 품질 상한선 비교

## 4. AudioScore Native

현재 저장소의 Native 경로는 모델 architecture/training scaffold이지, MR-MT3나 YourMT3+를 바로 대체할 수준의 pretrained checkpoint를 제공하는 경로가 아닙니다.

### 제품 관점

- 강점: 장기적으로 weights와 training provenance를 프로젝트가 완전히 소유 가능
- 약점: 고품질 다중 악기 transcription checkpoint를 만들 데이터와 GPU 학습 비용 필요
- 권장: 장기 R&D

## 5. 현재 권장 전략

```text
기본            MR-MT3
품질 모드        YourMT3+
내부 상한 비교    MuScriptor large (비상업 평가만)
장기 독립성       AudioScore Native
```

제품 출시 전에는 실제 타깃 곡으로 별도의 Golden Set을 만드는 것이 중요합니다.

권장 Golden Set:

- Pop/R&B 10곡
- Rock/J-Rock 10곡
- Worship/CCM 10곡
- Hip-hop 10곡
- Acoustic/Piano 10곡

각 곡에서 다음을 별도로 평가합니다.

1. 전체 note onset/offset F1
2. instrument assignment F1
3. drum transcription F1
4. bass note F1
5. melody/vocal-like part F1
6. 코드 정확도
7. 사람이 수정해야 하는 note 수 / 분
8. 실제 처리시간(real-time factor)

최종 엔진 선택은 논문 점수보다 **사용자가 완성 악보로 고치는 데 필요한 수정량**을 우선하는 것이 좋습니다.

## 공개 근거

- MR-MT3 paper: https://arxiv.org/abs/2403.10024
- YourMT3+ paper/leaderboard: https://paperswithcode.com/paper/yourmt3-multi-instrument-music-transcription
- MT3-Infer benchmark: https://github.com/openmirlab/mt3-infer
- MuScriptor model card: https://huggingface.co/MuScriptor/muscriptor-large
