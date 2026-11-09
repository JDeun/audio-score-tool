# 실제 보컬 40개: MR-MT3 / YourMT3+ 동일 조건 평가

Status: local real-model measurement; final model and commercial quality not approved.

## 입력과 실행

- 출처: Bittner et al. (2021), [vocadito v3](https://zenodo.org/records/5578807), DOI 10.5281/zenodo.5578807, CC BY 4.0. 40개의 원본 단성 보컬 녹음과 두 음악가의 독립 음표 주석 A1/A2를 모두 사용했다. 원본 ZIP MD5 `dea40fd18f14d899643c4ba221b33a46`와 개별 원음·주석 SHA-256을 두 실행에서 재확인했다.
- [실행 코드](../../scripts/run_vocadito_baseline.py), source commit `6b467b726cd92c16084150eaa02ac3b7e2f50dde`의 소스 SHA는 [전체 metadata-only 결과](VOCADITO_VOCAL_BASELINES_2026-11-09.json)에 기록했다. 원음·가사·음표 내용·예측 MIDI·체크포인트는 공개하지 않는다.
- 같은 Apple M4 arm64, Python 3.11.15, CPU, seed 0, torch threads 2에서 두 모델을 **순차** 실행했다. `mt3-infer==0.2.0`, torch/torchaudio 2.7.1, mir_eval 0.8.2를 고정했다. 어댑터 T5 API가 달라 transformers는 MR 4.57.6 / Your 4.44.2의 별도 환경이다.
- MR-MT3 checkpoint SHA `b8a3807ed265059abd25ad7f68142c06c35e8f6144dcaa45bd55946a3745398f`; YourMT3+ YPTF.MoE+Multi(noPS) SHA `ae38e415c79efd5592dcb9b658cdb99ddb11d4c4e1eaa364cab04a052473fc25`. 원본 revision과 실행 runtime은 결과 JSON에 있다. 자동 checkpoint 다운로드는 끄고 기존 program-preserving CLI를 사용했다.

각 환경에서 다음 명령을 사용했다. YourMT3+는 `--model yourmt3`와 독립 출력 경로로 같은 원본을 실행한다.

```bash
python -m scripts.run_vocadito_baseline \
  --archive /private/vocadito.zip --checkpoint-root /private/checkpoints \
  --model mr_mt3 --output /private/new-vocadito-mr-run
```

## 평가 방법과 결과

원래 주석의 시작·길이·Hz 음높이를 사용하며 음높이 반올림, pitch-class/octave 완화, 정답 기반 shift·시간 정렬을 하지 않았다. mir_eval의 onset 50ms, pitch 50cents, offset max(50ms, 정답 음표 길이의 20%)를 사용했다. A1/A2를 각각 평가하고 40개 녹음×2명의 F1을 동일 가중 평균했다. 빈 예측은 0점, 실행 실패는 실패로 남기는 규약이며 이번 두 실행은 각각 **40/40 성공, 실패 0, 빈 예측 0**이다.

| 모델 | A1 onset F1 | A2 onset F1 | 평균 onset F1 | 평균 onset+offset F1 |
| --- | ---: | ---: | ---: | ---: |
| MR-MT3 | 17.32% | 19.20% | 18.26% | 7.71% |
| YourMT3+ | 49.56% | 59.06% | 54.31% | 30.86% |

실측 전체 추론 시간은 MR 1,444.99초 / Your 809.70초다. 다른 개발 검사가 일부 동시 실행되었으므로 전용 하드웨어 지연 순위로 사용하지 않는다. 실행 시간·예측 개수·두 주석자의 점수와 체크섬을 곡별로 모두 JSON에 보존했다. 집계 전에 원본 ZIP의 각 audio/CSV와 두 실행의 SHA를 다시 대조했으며 보고된 macro를 개별 F1로 재계산했다.

## 판정과 남은 작업

이 데이터의 보컬 음표 인식은 YourMT3+가 더 높다. 하지만 **어느 모델도 이 결과만으로 최소 수정 출판 품질의 최종 모델로 승인하지 않는다.** 원음의 beat/downbeat/meter/key, 읽기 좋은 리듬, 반주 코드, 보컬 분리, 가사 정렬, 실제 PDF 가독성과 사람 수정 시간은 이 실험에서 측정하지 않았다. F1은 음표 정확도나 실제 수정 비율과 같지 않다.

이는 실제 솔로 보컬 평가이며, 기존 CocoChorales train 4곡의 악기 채보 점수를 보컬 성능으로 확대할 수 없음을 보여준다. 사전학습 중복은 미확인이므로 held-out 일반화 근거로 사용하지 않는다. 사용자 지정 최종 5곡은 실행·튜닝에 사용하지 않았다. 기본 엔진 설정·배포 승인·릴리스 번호를 바꾸지 않는다.

후속 조건: #200의 음악 구조·주선율·리듬 복원 구현, #34의 독립 정답과 수정량/시간 합격선, 사용 범위에 맞는 모델 적격성 및 최종 5곡 인수. #34/#172/#200은 이 보고서만으로 닫지 않는다.
