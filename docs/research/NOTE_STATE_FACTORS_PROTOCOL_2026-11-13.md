# Note-state HMM 가정별 진단 — 실행 전 고정 프로토콜

- 날짜: 2026-11-13 (Asia/Seoul)
- 실행 이슈: [#291](https://github.com/JDeun/audio-score-tool/issues/291)
- 기준 main: `80ce419eee2d73890f6dddbbb9cecfc6c68bff7a`
- 선행 결과: [#289 / #290 결과](NOTE_STATE_HMM_RESULTS_2026-11-13.md)
- 공개 구현 감사: [논문과 고정된 pYIN 소스의 차이](TONY_NOTE_HMM_SOURCE_AUDIT_2026-11-13.md)
- 상태: 이 파일과 구현·감사·테스트·workflow를 함께 commit한 뒤 최초 실행한다. 실제 frozen head와 checkout SHA는 Actions 및 결과 receipt에 기록한다. 결과를 본 뒤 이 파일을 수정하지 않는다.

## 질문과 범위

이전 HMM은 pYIN 유성 64,502프레임 중 31,575프레임을 Silent로 판정했고, offset 포함 F1은 pitch runs의 22.149227%보다 낮은 3.528561%였다. HMM 자체의 최소 길이 pruning은 0개였다. 이번 연구는 이 실패가 관측 분포와 상태 prior에 얼마나 민감한지, 다른 가정을 동시에 바꾸지 않고 조사한다. 이전 코드, 프로토콜, 결과, 원본 ZIP를 그대로 보존한다.

2015 Tony 논문의 식은 Gaussian PDF에 지수 0.1을 적용한다. 반면 Tony와 연결된 공개 pYIN 소스는 후보 확률에 지수 0.1을 적용하고 Gaussian PDF에는 적용하지 않는다. 이 차이는 2015년 v1.1 태그에도 존재한다. 이전 식을 단순 버그로 정정하거나 공개 소스 전체를 재현했다고 주장하지 않는다. 차이의 역사적 이유와 논문 평가 binary는 미확정이다. 근거와 revision별 세부 차이는 별도 소스 감사에 기록한다.

**주 가설:** 기존 joint 정규화에서 Gaussian exponent를 0.1에서 1로 바꾸면 과도한 Silent 선택이 줄어들고 기존 HMM 대비 pitch+onset+offset F1이 개선되는가? 개선이 관측되더라도 pitch runs 및 제품 채택 조건은 별도로 판단한다.

## 고정한 10개 corpus 조건

모든 신규 조건은 기존 `note_state_hmm`에서 표의 한 요인만 변경하며 RMS를 추가하지 않는다. 수치는 소스 감사 또는 사전 지정된 민감도 대비에서 정했고 synthetic/corpus 결과로 고르지 않는다.

| Arm | 기존 HMM 대비 변경 | 역할 |
|---|---|---|
| `pitch_runs` | 이전 구현 그대로 | 실용 기준선, 역사적 재현 |
| `pitch_hysteresis` | 이전 구현 그대로 | 역사적 재현 |
| `pitch_hysteresis_reattack` | 이전 구현 그대로 | 역사적 재현 |
| `note_state_hmm` | 이전 실패 설정 그대로 | 주 기전 비교 기준선 |
| `note_state_hmm_rms` | 이전 실패 설정과 RMS 그대로 | 실패·경계 삭제 보존 |
| `gaussian_exponent_1` | Gaussian PDF 지수 0.1 → 1 | **Primary** |
| `phase_balanced` | 양성 F0의 Attack/Stable을 각각 내부 정규화, 전체 질량 0.25/0.25 | 상태별 질량 배분 |
| `positive_voicing_08` | 양성 F0의 voiced 전체 질량 0.5 → 0.8 | 공개 단일 후보 경로의 한 수치 |
| `silent_self_099` | paper-scale Silent self 0.9999 → 0.99 | nominal exit 100배 민감도; 기존 hop 환산 유지 |
| `hop_unscaled` | 세 self probability의 시간 환산을 제거 | 동일 10ms 입력의 prior-clock 정책 민감도 |

Gaussian exponent 변경은 분포 폭과 joint 정규화 후 A/S 총질량을 함께 바꾼다. 이를 폭만 바꾼 실험이라고 부르지 않는다. Phase-balanced 조건의 A/S/U 총질량은 0.25/0.25/0.5이며 voiced 총량은 유지된다. Voicing 조건은 양성 입력에서만 바뀌고 zero-Hz 분기의 voiced floor `1e-12`는 그대로다. Hop 조건은 원논문의 44.1kHz/256-hop acoustic frontend를 실행하는 조건이 아니다. Self probability만 환산하면 전체 Viterbi가 sampling rate에 불변이라는 가정을 두지 않는다.

공통 불변값은 이전 프로토콜 그대로다: 16kHz, window 2048, hop 160, pYIN 55–880Hz, zero padding/centered clock; MIDI 33..81의 1/3-semitone 145개 pitch와 A/S/U 435개 상태; σA=5, σS=0.9; A→A/S, S→S/U, U→U/허용 A; 같은 pitch 또는 2/3..13 semitone jump와 `exp(-abs(delta)/2)` 조건부 kernel; 초기 A/U 각각 0.5, S=0; 종료 상태 자유, 동일 점수는 낮은 predecessor/state ID 우선. 원 self `.9/.99/.9999`의 시간 환산은 `p ** (.01 / (256/44100))`이다.

양성 raw MIDI의 median을 반올림한 정수 pitch, decoded pitch/voicing segment, 최소 80ms, 실제 audio duration clipping을 그대로 쓴다. 새로운 confidence threshold, tuning correction, gap fill, pitch range, 전이 kernel, 시작 prior, timestamp, annotation quantization은 도입하지 않는다. 공개 구현의 empty-candidate voiced 0.35, σS=0.8, all-Silent initialization, 207-pitch grid, Gaussian jump, fixed-lag decoding, raw-voicing readout gate, 100ms pruning 및 RMS 차이는 **이번에 함께 변경하지 않는 미검증 항목**이다.

## 단계 1: 고정한 245개 authored F0 조건

합성 입력은 알고 있는 F0 contour 자체다. 파형 합성이나 pYIN 추출 성능을 측정하지 않는다. Predictor에는 F0와 duration만 전달하고 case 종류, 정답, 대안 정답을 전달하지 않는다. 시간은 10ms 정수 프레임으로 만들며 입력 배열은 `duration / .01 + 1`개이다. Clip 끝까지 유성인 end/full 조건의 마지막 관측은 직전 F0를 유지하고 이벤트 offset만 duration에 맞춰 자른다. 인공적인 무성 한 프레임이 자유 종료를 강제 Silent 전이로 바꾸지 않도록 하는 계약이다. Interior/start/전체 무성 조건의 마지막 관측은 zero-Hz다. Interior의 양쪽 무성 padding은 각각 300ms다.

| 종류 | 사전 고정 격자 | 개수 |
|---|---|---:|
| 단음 | MIDI {33,45,57,69,81} × 길이 {80,120,200,300,500,800,1200}ms × {interior, clip 시작, clip 끝, clip 전체} | 140 |
| 동음 반복 | MIDI {45,57,69} × 각 음 길이 {120,300,800}ms × gap {0,10,20,50,100,300}ms, interior | 54 |
| pitch 변경 | 시작 MIDI {45,57,69} × 상승 {1,7,12}semitone × 각 음 길이 {120,500}ms × gap {0,50}ms, interior | 36 |
| 전체 무성 | 길이 {200,1000,2000}ms | 3 |
| 연속 contour | MIDI {45,57,69}, 1200ms, 6Hz ±0.3-semitone vibrato 또는 −0.3→+0.3-semitone 선형 drift | 6 |
| 관측 모호성 | MIDI {45,57,69}, 1200ms 음의 중간에 {10,50}ms zero-Hz | 6 |

합성 arm은 `pitch_runs`, 기존 HMM, 신규 5개로 7개다. 파형/RMS가 없는 조건에 RMS arm을 임의로 만들지 않는다. 245×7=1,715개 예측을 모두 저장한 뒤 점수를 계산한다. 모델이나 숫자를 바꾸지 않고 synthetic 다음에 corpus를 실행한다. 실행 오류가 없는 한 synthetic 성능이 나쁘다고 corpus 조건을 누락하지 않는다.

동음의 gap=0인 9개 조건은 한 긴 음과 두 재어택 음이 F0만으로 구별되지 않는다. 중간 zero-Hz 6개 조건도 실제 쉼/두 음과 추적 실패/한 음이 같은 관측을 가진다. 이 15개는 두 정답 해석을 모두 보존하고 정확도 평균에서 제외한다. 전체 무성 3개는 false positive 음표 수로 평가한다. 나머지 **227개**는 동일 가중의 onset 및 onset+offset F1을 보고한다. 전체 245개의 이벤트 수와 빈 출력을 모든 arm에 기록하고, 6개 HMM arm에는 raw-voiced coverage, Silent dropout, raw-unvoiced bridging, 최소 길이 필터 전후 손실을 추가한다. Ambiguous 조건의 임의 해석을 모델 실패나 성공으로 집계하지 않는다.

추가로 MIDI 5개에 대해 exponent {.1,1} × normalization {joint,balanced}의 **분석적 emission 총질량과 peak Stable/Silent 비율 20행**을 저장한다. 기존 self 전이를 포함한 Stable/Silent의 프레임별 log-weight 차이, 동일 pitch Silent→Attack 진입 비용, 합성 HMM 경로의 log-weight도 보존한다. 서로 다른 모델의 path log-weight를 보정된 confidence나 모델 간 정확도 지표로 쓰지 않는다. 이 분석은 decoded 성능의 factorial arm이 아니며, corpus에서 두 요인의 상호작용을 측정하지 않는다. 결정론적 격자에 모집단 신뢰구간을 붙이지 않는다.

## 단계 2: 동일한 40개 vocadito 재실행

[원본 vocadito ZIP](https://zenodo.org/records/5578807/files/vocadito.zip?download=1)은 58,492,257 bytes, MD5 `dea40fd18f14d899643c4ba221b33a46`으로 고정한다. `vocadito_1`..`vocadito_40`, A1/A2 모두 포함한다. 동일 WAV당 pYIN을 새로 한 번씩 실행한 뒤 모든 arm에 같은 F0를 전달한다. 과거 raw 배열을 재사용했다고 표현하지 않는다.

1. 40개 WAV만 읽는 prediction pass에서 400개 note JSON, 440개 observation/path 배열, raw WAV를 private workspace에 저장한다.
2. 모든 case·arm의 완결성 및 파일 hash를 확인하고 prediction manifest를 고정한다.
3. 그다음 처음으로 80개 note reference와 40개 F0 reference를 읽고 평가한다. 예측 JSON은 수정하지 않는다.
4. 평가 후 같은 manifest와 source/audio/observation identity를 다시 확인한다. 누락·실패·빈 예측은 숨기지 않는다. 빈 예측은 F1 0으로 남기고, 누락/실패 시 완결 aggregate를 내지 않는다.

Pitch tolerance 50 cents, onset 50ms, offset `max(50ms, reference duration×20%)`; octave 오류도 오류다. Reference Hz는 정수화하지 않는다. 기존 scorer의 파일별 F1 8자리 반올림과 파일·주석자 동일 가중 macro를 유지한다. 모든 arm에 onset/offset F1, precision/recall, prediction count, matched count, baseline 대비 reference gain/loss를 저장한다. Gain/loss는 최대 matching의 지표이며 사람의 오류 원인 라벨이 아니다.

**Primary:** `gaussian_exponent_1 − note_state_hmm`의 onset+offset F1. 파일별 `(A1+A2)/2` 차이 40개를 보고한다. 고정 `default_rng(291)`, 10,000회, shape `(10000,40)` recording index resampling, 선형 quantile 2.5/97.5%로 paired percentile 구간 하나를 계산한다. 주석자 80개나 음표 수천 개를 독립 표본으로 재표집하지 않는다. 이는 재사용 개발 표본의 기술적 불확실성 요약이며 미사용 데이터 일반화 검증이 아니다.

**실용 비교:** 각 arm과 `pitch_runs`의 onset 및 offset macro 차이, 개선/악화/동률 녹음 수, gained/lost reference를 함께 보고한다. 기존 HMM만 이긴 결과를 전체 성공으로 승격하지 않는다. 제품 후보로 논의하려면 최소한 runs 대비 offset macro가 증가하고 onset macro가 감소하지 않아야 한다. 이는 충분조건이 아니며, 미사용 녹음·사용자 편집 비용·악보 검증은 별도로 필요하다. 나머지 OAT 결과는 기존 설정에 조건부인 기술적 비교이며, 효과의 가산성이나 최적 조합을 주장하지 않는다.

## 역사적 재현과 독립 감사

기존 DSP ZIP `dsp-note-baseline-42989661618.zip`의 SHA256 `6bc477457a89403c7bb18f331d862555f4d963db4a227472bb19d63644d39541`와 HMM ZIP `note-state-hmm-43336542480.zip`의 SHA256 `46ea77a90750172a905750599db3b419f09d70d165ef0be221e0004b8cd61b26`을 직접 검증한다.

HMM receipt의 frozen 12개 source hash, 모든 source/reference/F0 평가, 이전 5개 arm의 **200개 예측 hash·개수·모든 주석자 점수**, 기존 6개 배열의 **240개 dtype/shape/raw-byte SHA256 identity**, 기존 diagnostics가 모두 일치해야 비교 gate가 통과한다. 이전 raw arrays 자체는 없지만 그 identity가 보존되어 있으므로 새 배열과 동일성을 확인할 수 있다. 어느 하나라도 다르면 계산 결과는 보존하되 exit nonzero 및 `baseline_parity_failed`로 처리한다.

별도 auditor는 새 runner/model/scorer를 import하지 않고 private 파일을 다시 읽어 다음을 확인한다: 40개 cohort/10개 arm/2명 주석자, 400개 note 파일, 440개 배열, source/reference hashes, 7개 HMM state path의 readout/coverage/pruning, 기존 RMS edit, 직접 mir_eval matching, aggregate, primary resampling, 두 역사적 receipt와의 parity. 기존의 엄격한 CSV/JSON·matching helper는 재사용할 수 있다. 이 감사는 private 결과와 계산의 일치를 검증하며, Viterbi 최적성은 별도의 dense-oracle unit test로 확인한다. 사후 파일 감사만으로 실제 reference 읽기 순서를 입증할 수 없으므로 그 순서는 실행 코드의 barrier 및 contract test와 함께 검토한다.

## 실행·실패·보존 규칙

CPU Ubuntu 24.04, Python 3.11, 2 threads, 최대 35분이다. 고정 runtime은 librosa 0.10.2.post1, NumPy 1.26.4, SciPy 1.13.1, numba 0.60.0, soundfile 0.13.1, resampy 0.4.2, soxr 1.1.0, mir_eval 0.8.2다. GPU, 학습, 모델 자격증명, 유료 추론은 사용하지 않는다. 기존 제품 dependency와 lockfile은 변경하지 않는다.

별도 workflow `cpu-note-state-factors.yml`는 PR opened/reopened 또는 명시적 dispatch에서만 실행한다. 결과 문서 commit 때문에 scientific run이 다시 실행되지 않게 한다. 실행 전 unit contract는 모델 구현의 수학·입력·tie·source parity와 barrier를 검증하며, 전체 합성 격자나 corpus 성능으로 설정을 선택하지 않는다.

공개 artifact allowlist는 `synthetic.json`, `vocadito.json`, `audit.json` 세 개다. 실제 녹음·human reference·full F0/path·실제 note JSON은 올리지 않는다. 직접 authored synthetic의 정답과 이벤트는 공개 metadata에 포함할 수 있다. 준비/추론/평가 오류도 `not_completed` 또는 `failed` receipt로 남기고 quality score를 꾸미지 않는다. 원본 Actions ZIP는 재압축하지 않고 checksum과 함께 보존한다.

실행 후에는 새 결과 문서와 receipt만 추가하고 frozen scientific files를 바꾸지 않는다. 오류 수정 재실행이 필요하면 실패 artifact와 변경 원인을 먼저 보존하고 새 실행으로 식별한다. 성능이 좋아도 제품 기본값·자동 보정은 바꾸지 않는다. [#281](https://github.com/JDeun/audio-score-tool/issues/281)의 같은 악보 복원, Melodyne/Flex Pitch의 audio 편집 품질, 폴리포닉 분석의 성능은 이번 실험에서 검증하지 않는다.
