# 채보 엔진 성능과 선택 기준

> 공개 benchmark는 dataset, metric, instrument mapping, checkpoint가 다르므로 서로 다른 표의 숫자를 단순 비교하면 안 됩니다. AudioScoreTool은 **속도보다 완성 악보까지 남는 수정량을 최소화하는 것**을 우선합니다.

## 결론

현재 정책은 다음과 같습니다.

```text
개인 / 비상업
    ↓
MuScriptor large   ← 품질 최우선 기본값
    ↓ fallback
YourMT3+
    ↓ fallback
MR-MT3

상용
    ↓
YourMT3+           ← 정확도 우선 후보, 배포 provenance 검토 필요
    ↓ safer fallback
MR-MT3             ← MIT 경로가 더 단순
```

`auto` preset도 v0.8부터 **Quality**로 해석합니다. Fast/Balanced는 사용자가 명시적으로 선택할 때만 사용합니다.

---

## 1. MuScriptor

MuScriptor는 Kyutai/Mirelo가 공개한 2026년 multi-instrument transcription 모델입니다. 170k 곡 규모의 다양한 실제/합성 음악 데이터와 post-training을 사용하며 실제 full-mix 일반화를 목표로 합니다.

공개 `D_Test` 비교에서 MuScriptor-large는 동일 평가에서 YourMT3+ baseline보다 큰 폭의 개선을 보고합니다.

| Model | Onset F1 | Frame F1 | Offset F1 | Drums F1 | Multi F1 |
|---|---:|---:|---:|---:|---:|
| YourMT3+ baseline | 32.5 | 45.5 | 17.8 | 41.4 | 21.9 |
| MuScriptor large | 60.4 | 72~73 | 48~49 | 49~50 | 약 48 |

이 수치는 Slakh2100/URMP/AMT Challenge와 **평가셋이 다르므로 직접적인 절대 비교값은 아닙니다.** 논문은 외부 unseen dataset에서도 일부 frame/multi F1 개선을 보고하지만 onset/offset은 장르에 따라 여전히 어렵다고 설명합니다.

### AudioScoreTool 정책

- `usage_mode=personal`의 기본 엔진
- 기본 모델: `large`
- 장점: 현재 지원 후보 중 실제 혼합음원 품질 상한을 가장 우선하기 좋은 선택
- 단점: 1B급 모델로 연산량/VRAM/latency 부담이 큼
- 라이선스: 코드 MIT, 공개 weights **CC BY-NC 4.0**
- 따라서 **상용 모드에서는 API와 UI 모두 선택을 차단**

개인 사용에서는 Hugging Face에서 weights 라이선스를 수락한 뒤 인증해야 합니다.

---

## 2. YourMT3+

YourMT3+ `YPTF.MoE+M` 계열은 공개 Slakh2100 결과에서 Onset F1 약 **84.56**, Multi F1 약 **74.84**를 보고하며 MT3 계열 baseline보다 강한 성능을 보입니다. URMP에서도 Onset F1 약 **81.79**, Multi F1 약 **67.98**가 보고되었습니다.

2025 AMT Challenge 결과에서는 YourMT3 계열이 강한 상위권을 유지했으며, 우승 MIROS가 YourMT3+를 pretrained encoder로 확장해 근소하게 앞섰습니다. 다만 해당 challenge는 주로 classical transcription 조건이며, AudioScoreTool의 pop/rock/worship/hip-hop 타깃 전체를 대표하지는 않습니다.

### AudioScoreTool 정책

- MT3 계열에서 **정확도 우선 모델**
- MuScriptor 사용이 허용되지 않는 상용 모드의 첫 번째 품질 후보
- MR-MT3보다 느리고 checkpoint가 큼
- checkpoint Hugging Face metadata와 `mt3-infer` vendored implementation은 Apache-2.0으로 표기
- 공식 YourMT3 GitHub 저장소는 GPL-3.0으로 표시되므로 **상용 배포 시 고정 revision 단위 provenance 검토 필요**

즉 개인 사용에는 적극 권장할 수 있고, 상용에서는 기술적으로 사용 가능성이 높은 후보지만 법률/배포 검토 없이 “완전 permissive”라고 단정하지 않습니다.

---

## 3. MR-MT3

MR-MT3는 MT3의 instrument leakage를 줄이기 위해 이전 segment의 memory를 유지하는 구조를 추가합니다. Slakh2100에서 onset F1 개선과 leakage 감소를 보고했습니다.

MT3-Infer가 공개한 RTX 4090 benchmark에서는 약 **57× real-time**, checkpoint 약 **176 MB**로 소개되어 매우 빠른 편입니다.

### AudioScoreTool 정책

- 정확도보다 배포 단순성/속도/작은 checkpoint가 중요할 때 fallback
- 원 구현 및 공개 checkpoint가 MIT로 표시되어 상용 provenance가 상대적으로 단순
- 최고 품질 우선 정책에서는 기본값이 아님

---

## 4. MIROS (2025 AMT Challenge winner)

2025 AMT Challenge에서 MIROS는 F1 약 **0.5998**로 YourMT3-YPTF-MoE-M의 약 **0.5938**을 근소하게 앞선 우승 모델로 보고되었습니다. 공개 저장소는 YourMT3+ framework에 pretrained encoder를 결합한 구조라고 설명합니다.

그러나 AudioScoreTool 기본 provider로 바로 채택하지 않는 이유는 다음과 같습니다.

1. challenge 평가가 AudioScoreTool의 실제 장르 분포와 다름
2. production inference wrapper/checkpoint 배포 안정성이 MT3-Infer/MuScriptor보다 덜 검증됨
3. 상용 배포에 필요한 명시적 라이선스/provenance를 먼저 고정해야 함

따라서 **Golden Set 후보 엔진**으로 추적하되, 현재 기본 provider에는 넣지 않습니다.

---

## 5. AudioScore Native

현재 Native 경로는 architecture/training scaffold입니다. 공개 SOTA 모델을 바로 대체할 pretrained checkpoint가 아닙니다.

- 강점: 장기적으로 weights와 training provenance를 프로젝트가 완전히 소유 가능
- 약점: 고품질 다중 악기 데이터와 상당한 GPU 학습 비용 필요
- 권장: 장기 R&D

---

## 6. 제품용 Golden Set

공개 leaderboard보다 중요한 KPI는 **“최종 판매/사용 가능한 악보까지 사람이 얼마나 고쳐야 하는가”**입니다.

권장 50곡 세트:

- Pop/R&B 10곡
- Rock/J-Rock 10곡
- Worship/CCM 10곡
- Hip-hop 10곡
- Acoustic/Piano 10곡

각 곡에서 다음을 기록합니다.

1. note onset/offset F1
2. instrument assignment F1
3. drum F1
4. bass F1
5. melody/vocal-like part F1
6. chord accuracy
7. 가사 attachment/alignment accuracy
8. 사람이 수정한 note 수 / 음악 1분
9. 사람이 수정한 chord 수 / 음악 1분
10. 최종 악보까지의 실제 편집 시간
11. real-time factor / peak VRAM
12. LLM/규칙 검증이 실제 오류를 얼마나 잘 우선순위화했는지

최종 선택 기준은 8~10번을 가장 높은 가중치로 두는 것을 권장합니다.

---

## 공개 근거

- MuScriptor project/paper: https://muscriptor.github.io/ , https://github.com/muscriptor/muscriptor
- MuScriptor weights/license: https://huggingface.co/MuScriptor/muscriptor-large
- YourMT3+ paper: https://arxiv.org/abs/2407.04822
- YourMT3+ code: https://github.com/mimbres/YourMT3
- YourMT3+ checkpoint: https://huggingface.co/mimbres/YourMT3
- MR-MT3 paper: https://arxiv.org/abs/2403.10024
- MT3-Infer: https://github.com/openmirlab/mt3-infer
- 2025 AMT Challenge results: https://arxiv.org/abs/2603.27528
- MIROS repository: https://github.com/amt-os/ai4m-miros
