# Tony note HMM 공개 소스 감사 — 논문·구현 차이와 후속 실험 범위

검토일: 2026-11-13. 후속 연구 [#291](https://github.com/JDeun/audio-score-tool/issues/291).
비교 기준 main: `80ce419eee2d73890f6dddbbb9cecfc6c68bff7a`.
앞선 [동결 프로토콜](NOTE_STATE_HMM_PROTOCOL_2026-11-13.md)과
[완료된 성능 하락 결과](NOTE_STATE_HMM_RESULTS_2026-11-13.md)는 그대로 보존한다.
다음 실행의 계약과 arm ID는
[요인별 진단 프로토콜](NOTE_STATE_FACTORS_PROTOCOL_2026-11-13.md)에 기록한다.

## 결론과 증거의 범위

**앞선 adaptation의 Gaussian PDF 지수 0.1, voiced mass 0.5, Stable 표준편차
0.9는 2015년 Tony 논문에 실제로 기재된 값이다. 공개 소스와 다르다는 이유로
이 선택을 사후에 구현 버그라고 바꾸어 해석하지 않는다.** 반면 Tony가 연결하는
pYIN 공개 코드에서는 후보 확률에만 0.1 제곱을 적용하고 Gaussian PDF에는
그 지수를 적용하지 않는다. voiced mass와 Stable 표준편차도 다르다. [P1] [S3] [S4]

이 불일치는 현재 pin된 2020년 소스에서만 발견되는 변경이 아니다. Tony 1.0과
대응한다고 변경 이력에 명시된 pYIN v1.1의 2015년 태그에도 같은 emission
형태와 파라미터가 존재한다. 논문과 소스가 다른 이유, 논문의 평가에서 사용한
실행 파일의 정확한 revision은 이번 감사로 확인되지 않았다. [S2] [H1] [H2]

이번 문서는 공개 원문의 읽기 전용 검토와 현재 저장소의 명시적 계약 비교다.
upstream GPL 소스의 코드 조각을 저장소로 복사하지 않았으며, 아래 수식과 설명은
관찰한 동작을 새로 정리한 것이다. 소스 감사 자체는 새 성능 측정이 아니다.
원본 프로그램 실행, 동일 오디오에 대한 Tony 재현, 실데이터 재추론을 수행했다는
주장을 하지 않는다. 측정 결과와 실행 영수증은 후속 결과 문서에 둔다.

## 1. 공식 출처 연결과 고정 revision

공식 [Tony 안내](https://www.sonicvisualiser.org/tony/)와
[프로젝트 설명](https://isophonics.net/tony.html)은 Tony의 분석에 pYIN Vamp
plugin을 사용한다고 설명한다. Tony 저장소의 dependency 선언은 `pyin`을
GitHub `c4dm` 소유 저장소로 연결하며, lock은 다음 commit을 지정한다. [S1]

| 검토 대상 | 고정 Git commit | commit 시각, UTC | 확인할 수 있는 범위 |
|---|---|---|---|
| Tony `default` 검토 시점 | `8fb33900ea77e51796d4f0618bc338c89d82acf0` | 2024-07-02 17:24:59 | 해당 tree의 dependency pin과 분석 설정 |
| 그 Tony lock의 pYIN | `1d68cac9c5ecb1d81054d25d90158e5838dd78c2` | 2020-02-06 15:02:47 | 아래 표와 수식의 주된 구현 근거 |
| 역사 비교용 pYIN `v1.1` 태그 | `f9c4283e6d1b8258634883d944a1cb4f0a6aea6f` | 2015-04-21 11:54:31 | 논문과 동시기 공개 소스에도 emission 차이가 존재함 |

시각은 GitHub commit 메타데이터의 author/committer 값이며 공개 릴리스 일자를
대신하지 않는다. pYIN `CHANGELOG`는 v1.2를 Tony v2.1에서 사용한 버전과,
v1.1을 Tony v1.0에서 사용한 버전과 대응시킨다. 현재 설치된 바이너리나 논문
평가 바이너리의 동일성을 직접 검증한 것은 아니다. [S2] [C1] [C2] [C3]

핵심 파일의 Git blob SHA-1을 아래에 남긴다. 이는 Git 파일 객체의 해시이며
raw 파일 바이트의 SHA256으로 표기하지 않는다. 나머지 참조 파일도 모든 링크를
같은 commit에 고정했다. 공개 코드를 연구 저장소에 vendor하거나 사본으로
첨부하지 않고 upstream permalink와 식별자로 추적한다.

| 파일 / revision | Git blob SHA-1 |
|---|---|
| Tony `repoint-lock.json`, 위 Tony commit | `d3404c23df10384c026d28492020204916736482` |
| pYIN `MonoNoteHMM.cpp`, 2020 pin | `f5a2c20c70bf58af5f34c6cb6bd22bfb5bad07cb` |
| pYIN `MonoNoteParameters.cpp`, 2020 pin 및 v1.1 공통 | `8d9c9508fac6b658550609ced428256925fc3811` |
| pYIN `PYinVamp.cpp`, 2020 pin | `a012e030ed4af8ca242a5944849b98dcd3c0afd3` |
| pYIN `MonoNoteHMM.cpp`, v1.1 | `9abd92af115a37fc79b3b41d4a5499c667a43956` |
| pYIN `PYinVamp.cpp`, v1.1 | `ebfa6a2472609655c4c6bcc71c39bd6915646c61` |

## 2. Note HMM이 실제로 받는 입력

pYIN의 첫 번째 pitch HMM과 두 번째 note HMM을 구별해야 한다. 감사한 plugin의
일반 note 출력 경로는 최종 smoothed F0가 양수이면 fractional MIDI로 변환한
후보 **한 개**에 상수 확률 `0.9`를 붙인다. 양수가 아니면 빈 후보 목록을 만든다.
따라서 note HMM에 전체 pYIN 후보 posterior가 반드시 필요하다고 단정할 수
없다. 이 경로 자체가 이미 단일 smoothed F0로 축약된 입력을 사용한다. [S5]
2015년 v1.1에서도 같은 경로를 확인했다. [H3]

첫 pitch HMM의 unvoiced 상태에는 음수 frequency 표지가 있다. plugin은 그 signed
frequency를 note 처리용 내부 배열에 먼저 저장한 뒤, 외부 pitch 출력 설정에
따라 숨기거나 절댓값을 표시한다. note 입력을 만드는 조건은 여전히 내부 값이
양수인지 여부다. 즉 외부 `outputunvoiced` 표시 옵션이 음수 값을 note 입력의
양성 후보로 바꾸는 것은 아니다. voiced 상태인데 대응 후보가 없으면 frequency
반환값이 0일 수도 있으며, 이 역시 빈 note 후보가 된다. [S6] [S7]

별도 `voicedprob` 출력은 note emission에 직접 전달되지 않는다. 이는 **고정된
최종 F0를 조건으로 한 note 단계**의 설명이다. 후보 확률과 voicing 판단이 앞선
pitch HMM에 미치는 간접 영향까지 없다는 뜻은 아니다. [S5] [S7]

## 3. 공개 소스의 emission과 논문 수식

### 공개 소스의 질량 배분

후보들의 확률을 `c_j`, 피치를 `q_j`, pitch grid 크기를 `N`이라고 하자.
소스의 전체 non-silent 질량은 다음과 같다. [S3] [S4]

$$
v = (1-0.5)\sum_j c_j + 0.5\times0.7.
$$

각 Attack/Stable 상태 `s`는 자기 중심 피치에 가장 가까운 후보 `j(s)`를 택한다.
그 상태의 정규화 전 가중치는 다음과 같다. 표준편차는 Attack 5 semitones,
Stable 0.8 semitones다.

$$
w_s = c_{j(s)}^{0.1}\,
      \mathcal{N}(q_{j(s)};\mu_s,\sigma_s),\qquad
e_s = v\frac{w_s}{\sum_{r\in A\cup S}w_r}.
$$

분모는 **모든 Attack와 Stable, 총 `2N` 상태**를 합친다. 각 Silent 상태에는
`(1-v)/N`을 준다. 후보가 여러 개인 일반 함수에서는 가장 가까운 후보를 고르는
연산과 그 후보의 확률이 의미를 갖는다. 다만 실제 note 경로의 양성 입력은
항상 `(q, 0.9)` 한 개이므로 `v=0.8`이고, `0.9^0.1`은 모든 non-silent 상태의
공통 인자라 joint 정규화에서 상쇄된다. `0.9`는 `v` 계산에는 여전히 남는다.
Gaussian PDF 자체가 `0.1` 제곱되는 것은 아니다. [S3] [S5]

후보가 없으면 소스는 모든 non-silent 임시 가중치를 1로 둔다. 따라서 다음과
같이 균등하게 나뉜다. [S3]

$$
v=0.35,\qquad e_{A_p}=e_{S_p}=\frac{0.35}{2N},\qquad
e_{U_p}=\frac{0.65}{N}.
$$

이 prior는 무성 입력에서 non-silent 가능성을 0으로 만들지 않는다. 그러나
**최종 note readout은 해당 프레임에 양성 smoothed F0가 있는지도 다시 요구**한다.
따라서 note HMM의 non-silent 경로만 보고 원본이 무성 gap을 그대로 note에
포함한다고 해석하면 안 된다. 현재 adaptation의 gap 포함 가능성은 이 최종
조건과도 다른 계약이다. [S8]

### 논문과 기존 adaptation의 근거

2015년 논문 §3.2 Eq.1은 Gaussian PDF에 직접 `tau=0.1`을 적용하고, voiced prior
`v=0.5`, Stable 표준편차 `0.9`를 기재한다. 기존 adaptation은 이 세 값을 따르며,
정규화를 `2N` 전체에 적용하는 방식을 명시적으로 동결했다. 논문에 없는
무성 입력 처리 등은 별도 adaptation이라고 이미 밝혀 두었다. [P1]

2015년 v1.1 소스도 후보 확률에만 지수를 적용한다. 그 버전의 파라미터 파일은
2020 pin과 blob 자체가 같다. 따라서 불일치를 단순히 2020년 버전 변경의 결과로
설명할 근거도 없다. **논문 설명과 두 공개 소스 revision의 차이를 기록하는 것**이
가능한 결론이며, 어느 쪽이 논문의 실제 평가를 지배했는지는 미확정이다. [H1] [H2]

지수 변경은 폭만 조절하는 한 가지 효과로 환원되지 않는다. 연속 전구간에서
Gaussian PDF의 `tau` 제곱을 적분한 값은 `sigma^(1-tau)`에 비례한다. 그러므로
joint 정규화에서 `tau=0.1`은 넓은 Attack 분포에 더 큰 총질량을 배분할 수 있다.
`tau=1`에서는 두 Gaussian의 전구간 적분이 같아진다. 유한 pitch grid에서는
경계 절단과 이산 합산도 작용한다. 이 관계는 수식의 분석적 성질이며 실제
녹음에서 recall 저하를 얼마나 설명하는지는 후속 실험으로 측정해야 한다.

## 4. 현재 adaptation과 공개 소스의 차이

아래 upstream 열은 별도 표기가 없으면 **2020 pYIN pin**을 뜻한다. 전체 Tony
재현 체크리스트를 충족했다고 주장하기 위한 표가 아니라, 다음 실험에서 바꾸는
요인과 남겨 두는 차이를 식별하기 위한 표다. [S3]–[S12]

| 항목 | 감사한 공개 소스 | 기존 adaptation |
|---|---|---|
| 양성 입력 | smoothed F0 한 후보, 확률 0.9 | 최종 gated F0 한 값 |
| Gaussian 지수 | PDF 그대로; 후보 확률만 0.1 제곱 | PDF 자체 0.1 제곱 |
| 양성 F0의 non-silent 총질량 | 0.8 | 0.5 |
| 무성 입력의 non-silent 총질량 | 0.35, `2N`에 균등 | `1e-12`, `2N`에 균등 |
| emission 정규화 | Attack/Stable 전체 `2N`에 joint | 같은 joint 범위이나 가중치·질량이 다름 |
| Attack / Stable 표준편차 | 5 / 0.8 semitones | 5 / 0.9 semitones |
| 초기 상태 질량 | Silent 전체에 1, pitch별 균등 | Attack 0.5, Silent 0.5, 각각 pitch별 균등 |
| pitch grid | `35+i/3`, `i=0..206`: 207 pitches, 621 states | `33+i/3`, `i=0..144`: 145 pitches, 435 states |
| 상태 전이 구조 | A→A/S, S→S/U, U→U/A | 같은 위상 구조 |
| self probabilities | 프레임당 0.9 / 0.99 / 0.9999 | 위 값을 10 ms hop에 맞춰 지수 환산 |
| Silent→Attack jump kernel | 거리의 Gaussian PDF, 표준편차 0.7 | `exp(-abs(delta)/2)` |
| 허용 jump | 같은 pitch 또는 `0.5 < abs(delta) < 13` | 같은 pitch 또는 2/3 이상, 13 포함 |
| 기본 note decoding | fixed lag 1000 frames; 옵션 off면 full Viterbi | full Viterbi |
| 마지막 note pitch | 양성 fractional MIDI의 upper median을 연속 Hz로 출력 | NumPy median 후 `rint`, 정수 MIDI |
| 최종 raw-unvoiced 조건 | 양성 raw smoothed F0가 없는 프레임을 제외 | decoded segment에 raw-unvoiced 프레임 포함 가능 |
| RMS 조건 | `level[j]/level[j+2] > s`인 프레임만 유지; 마지막 두 프레임 예외 | 별도 RMS arm에서 `rms[i-1]/rms[i+1] < .7`이면 `i-2`를 Silent로 변경 |
| RMS와 신호 계약 | pYIN이 만든 level, 기본 `s=.7`; Tony 설정으로 변경 가능 | centered 2048-sample RMS, zero padding; 분모가 `1e-12`보다 클 때만 검사; RMS 없는 기본 arm도 유지 |
| note timestamp, 초 | 기본 `(frame*hop + block/4)/sample_rate`; precise에서는 `block/2` | centered F0 clock의 `frame*0.01`, 끝은 waveform 길이로 clip |
| 최소 길이 기본값 | 100 ms | 80 ms |
| 음향 분석 clock | Tony 44.1 kHz, block 2048, hop 256 | 기존 librosa pYIN 16 kHz, block 2048, hop 160 |

공개 소스는 Silent 상태를 이전 pitch의 기억으로 유지하며, 다음 Attack으로
갈 때만 pitch를 바꾼다. self probability와 jump 가중치는 outgoing row별로
질량을 보존하지만, 소스 안에 sample rate나 hop에 따른 self probability 환산은
없다. Tony는 resampling과 256/2048 설정을 별도 계층에서 지정한다. [S3] [S11] [S12]

원본 readout의 median은 정렬 후 index `size/2`를 고른다. 짝수 개 샘플에서는
가운데 두 값을 평균하는 NumPy median과 다르며 정수 MIDI quantization도 없다.
마지막 프레임은 note를 flush하는 분기로 들어가 그 프레임의 pitch를 median
수집에 추가하지 않는 경계 동작도 존재한다. [S8]

RMS는 단순히 같은 threshold를 쓴다고 동등해지지 않는다. 현재 규칙에서
`j=i-2`로 놓으면 검사하는 값은 `rms[j+1]/rms[j+3]`인 반면, 공개 소스의 최종
유지 조건은 `level[j]/level[j+2]`다. equality 처리, 무성 F0의 최종 조건,
RMS 신호의 생성 경로도 함께 다르다. [P1] [S8]

논문은 MIDI 35–85, semitone당 3칸과 207 pitches를 함께 적지만 수가 맞지 않는다.
공개 소스의 `minPitch=35`, `nS=69`, `nPPS=3`을 계산하면 실제 grid 끝은
MIDI `103+2/3`이며 207 pitches와 621 states가 된다. `MonoNote.cpp`의 681 states
주석도 `69*3*3`과 맞지 않는 산술 오류다. 여기서 확정하는 것은 고정 revision의
실제 파라미터이지 논문의 범위를 소급 수정한 해석이 아니다. [P1] [S4] [S9]

## 5. 이번 후속 연구가 바꾸는 것과 남겨 두는 것

후속 실데이터 비교는 기존 세 segmenter와 `note_state_hmm`,
`note_state_hmm_rms`를 보존하고 다음 다섯 arm을 추가하여 총 10개로 고정한다.
새 arm은 모두 **기존 RMS 없는 `note_state_hmm` 하나를 기준으로 한 요인만**
바꾸며, 서로의 변경을 합치지 않는다. 정확한 실행·평가 계약은
[새 프로토콜](NOTE_STATE_FACTORS_PROTOCOL_2026-11-13.md)이 우선한다.

| 새 arm | 단독으로 바꾸는 항목 | 검토하는 질문 |
|---|---|---|
| `gaussian_exponent_1` — primary | 양성 F0의 Gaussian PDF 지수만 0.1→1; joint 정규화와 총질량 0.5 유지 | 공개 소스에서 확인한 PDF 형태가 기존 adaptation의 정규화·경로에 미치는 영향 |
| `phase_balanced` | 양성 F0에서 Attack와 Stable을 각각 정규화하여 총질량 0.25/0.25 부여; Silent 0.5 | joint 정규화의 위상별 질량 편향에 대한 진단 |
| `positive_voicing_08` | 양성 F0의 non-silent 총질량만 0.5→0.8, Silent 0.2 | 공개 소스의 양성 질량과 대응하는 단독 비교 |
| `silent_self_099` | 환산 전 Silent self probability만 0.9999→0.99; 기존 hop 환산 유지 | 높은 Silent 지속성의 영향 |
| `hop_unscaled` | 세 self probability를 0.9/0.99/0.9999 그대로 10 ms마다 사용 | 기존 clock 환산 선택의 영향 |

모든 새 arm의 무성 입력 emission은 기존 `1e-12` 계약을 유지한다. phase-balanced
arm도 양성 입력에서만 별도 위상 정규화를 적용한다. `silent_self_099`의 0.99는
공개 소스의 Silent 값이 아니며 연구를 위한 진단값이다. `hop_unscaled`는
upstream의 프레임당 수치를 쓰지만 hop이 여전히 10 ms이므로 원본의 초당 지속성을
재현하지 않는다. phase-balanced 역시 upstream과 같은 구현이라고 주장하지 않는다.

새 arm의 출력 pitch, 음향 관측, grid, 초기 분포, jump kernel, Stable 표준편차,
최소 길이, timestamp, 무성 구간의 최종 readout과 decoder lag 계약은 그대로다.
새 RMS 조합, 0.35 무성 prior, upper median, Gaussian jump kernel, upstream
초기화·grid·raw gate·timestamp를 함께 도입하는 비교는 이번에 하지 않는다.
따라서 새 arm 하나가 개선되어도 Tony 전체 구현의 우수성이나 완전 재현을 뜻하지
않으며, 실패해도 upstream 구현 전체를 기각하는 근거가 되지 않는다.

소유한 합성 F0의 245개 사례는 경계 위치, 길이, 같은 pitch의 gap, pitch 변화,
무성 입력, 작은 vibrato/drift와 dropout을 점검한다. 실제 음향 추정기를 거치지
않으므로 여기서 검증되는 것은 관측 이후의 decoder 동작이다. 파형 없는 사례에
새 RMS를 만들어 붙이지 않고 `pitch_runs`, 기존 HMM, 새 다섯 요인 arm의 7개
방법만 비교한다. 같은 pitch의 zero-gap 쌍 9개와 dropout 6개는 서로 다른 event
해석이 동일 F0를 만들 수 있어 F1 cohort에서 제외한다. truth가 비어 있는 silence
3개도 F1 평균에서 분리하되 false-positive event를 반드시 기록한다. 모든 245개
사례의 출력과 count/coverage를 보존하고, 나머지 227개에서 고정된 F1을 보고한다.

분석적 emission 질량의 2×2 비교는 허용하지만, 결합한 요인의 성능 arm이나
성능 interaction 측정으로 부르지 않는다. 결과를 본 뒤 유리한 요인들을 합치거나
곡별 최선 arm을 고르지 않는다. 기존 성능 하락 결과를 지우지 않고, 같은 개발 집합의
재사용·정수 pitch 표현·performed-note 평가라는 한계를 유지한다. 제품 활성화,
새 holdout 일반화, 상용 편집기의 내부 검출기, 오디오 재합성이나 written-score
복원은 이 소스 감사와 후속 요인 연구의 검증 대상이 아니다.

## 일차 출처

논문은 DOI와 공식 proceedings PDF를 함께 기록했다. 코드 링크는 branch 이름이
아닌 full commit에 고정했다. GitHub API에서 file blob SHA와 commit 시각을 읽고
해당 파일의 내용을 대조했다. 날짜가 다른 문헌 사이의 차이는 위에서 구분했다.

- [P1] Mauch et al. (2015), *Computer-aided Melody Note Transcription Using the
  Tony Software: Accuracy and Efficiency*, TENOR, §3.1–3.3, §4.1.
  [공식 PDF](https://www.tenor-conference.org/proceedings/2015/04-Mauch-Tony.pdf),
  [DOI](https://doi.org/10.5281/zenodo.1289635).
- [S1] Tony dependency
  [owner 선언](https://github.com/sonic-visualiser/tony/blob/8fb33900ea77e51796d4f0618bc338c89d82acf0/repoint-project.json#L89-L93),
  [pYIN lock](https://github.com/sonic-visualiser/tony/blob/8fb33900ea77e51796d4f0618bc338c89d82acf0/repoint-lock.json#L48-L50).
- [S2] pYIN [CHANGELOG, v1.2/v1.1과 Tony의 관계](https://github.com/c4dm/pyin/blob/1d68cac9c5ecb1d81054d25d90158e5838dd78c2/CHANGELOG#L2-L29).
- [S3] pYIN `MonoNoteHMM.cpp`:
  [emission](https://github.com/c4dm/pyin/blob/1d68cac9c5ecb1d81054d25d90158e5838dd78c2/MonoNoteHMM.cpp#L35-L96),
  [초기 상태·전이](https://github.com/c4dm/pyin/blob/1d68cac9c5ecb1d81054d25d90158e5838dd78c2/MonoNoteHMM.cpp#L114-L198).
- [S4] pYIN [MonoNoteParameters.cpp, 기본 파라미터](https://github.com/c4dm/pyin/blob/1d68cac9c5ecb1d81054d25d90158e5838dd78c2/MonoNoteParameters.cpp#L16-L39).
- [S5] pYIN [PYinVamp.cpp, 단일 smoothed F0의 note 입력](https://github.com/c4dm/pyin/blob/1d68cac9c5ecb1d81054d25d90158e5838dd78c2/PYinVamp.cpp#L612-L636).
- [S6] pYIN `MonoPitchHMM.cpp`:
  [signed grid](https://github.com/c4dm/pyin/blob/1d68cac9c5ecb1d81054d25d90158e5838dd78c2/MonoPitchHMM.cpp#L35-L42),
  [nearest frequency](https://github.com/c4dm/pyin/blob/1d68cac9c5ecb1d81054d25d90158e5838dd78c2/MonoPitchHMM.cpp#L163-L197).
- [S7] pYIN `PYinVamp.cpp`:
  [voiced probability 출력](https://github.com/c4dm/pyin/blob/1d68cac9c5ecb1d81054d25d90158e5838dd78c2/PYinVamp.cpp#L539-L551),
  [내부 signed F0와 외부 출력](https://github.com/c4dm/pyin/blob/1d68cac9c5ecb1d81054d25d90158e5838dd78c2/PYinVamp.cpp#L584-L606).
- [S8] pYIN [PYinVamp.cpp, raw-F0/RMS gate, 길이, median, timestamp](https://github.com/c4dm/pyin/blob/1d68cac9c5ecb1d81054d25d90158e5838dd78c2/PYinVamp.cpp#L652-L705).
- [S9] pYIN [MonoNote.cpp, fixed lag와 상태 readout](https://github.com/c4dm/pyin/blob/1d68cac9c5ecb1d81054d25d90158e5838dd78c2/MonoNote.cpp#L24-L85).
- [S10] pYIN `PYinVamp.cpp`:
  [plugin defaults](https://github.com/c4dm/pyin/blob/1d68cac9c5ecb1d81054d25d90158e5838dd78c2/PYinVamp.cpp#L30-L50),
  [초기화·pitch lag·frame 처리](https://github.com/c4dm/pyin/blob/1d68cac9c5ecb1d81054d25d90158e5838dd78c2/PYinVamp.cpp#L412-L467).
- [S11] Tony [MainWindow.cpp, resampling 44.1 kHz](https://github.com/sonic-visualiser/tony/blob/8fb33900ea77e51796d4f0618bc338c89d82acf0/main/MainWindow.cpp#L155-L156).
- [S12] Tony [Analyser.cpp, 분석 설정과 256/2048 clock](https://github.com/sonic-visualiser/tony/blob/8fb33900ea77e51796d4f0618bc338c89d82acf0/main/Analyser.cpp#L416-L472).
- [H1] pYIN v1.1 [MonoNoteHMM.cpp, 역사적 emission](https://github.com/c4dm/pyin/blob/f9c4283e6d1b8258634883d944a1cb4f0a6aea6f/MonoNoteHMM.cpp#L38-L91).
- [H2] pYIN v1.1 [MonoNoteParameters.cpp, 동일 blob인 파라미터](https://github.com/c4dm/pyin/blob/f9c4283e6d1b8258634883d944a1cb4f0a6aea6f/MonoNoteParameters.cpp#L16-L39).
- [H3] pYIN v1.1 [PYinVamp.cpp, 단일 F0 입력과 readout](https://github.com/c4dm/pyin/blob/f9c4283e6d1b8258634883d944a1cb4f0a6aea6f/PYinVamp.cpp#L543-L600).
- [C1] [Tony commit 메타데이터](https://api.github.com/repos/sonic-visualiser/tony/commits/8fb33900ea77e51796d4f0618bc338c89d82acf0).
- [C2] [pYIN pin commit 메타데이터](https://api.github.com/repos/c4dm/pyin/commits/1d68cac9c5ecb1d81054d25d90158e5838dd78c2).
- [C3] [pYIN v1.1 resolve 결과의 commit 메타데이터](https://api.github.com/repos/c4dm/pyin/commits/f9c4283e6d1b8258634883d944a1cb4f0a6aea6f).
