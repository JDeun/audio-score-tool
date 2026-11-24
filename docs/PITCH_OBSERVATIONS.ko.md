# 보컬 pitch 관측 형식

`vocal/pitch.npz`는 음표 편집 결과와 별도로 보존하는 고정 Tiny 검증 모델의 관측이다.
버전은 `pitch.runtime.json`의 정수 `schema_version`으로 구분한다. 모델의 설정·runtime,
체크포인트·adapter·입력 WAV·출력 archive 해시는 기존 receipt 계약을 유지한다.
새 라이브 실행은 버전 2만 허용한다.

## 버전 2

archive에는 다음 다섯 배열만 있다. 모두 길이가 같은 1차원 수치 배열이다.

| 배열 | 의미 |
| --- | --- |
| `times` | 디코딩한 보컬 시작을 0으로 둔 초 단위 분석 시각, `arange(T) * .01` |
| `raw_hz` | 고정 Viterbi decoder를 거친 F0(Hz), voicing/음량 필터 적용 전 |
| `periodicity` | 모델이 반환한 해당 pitch의 주기성 점수, 유한한 0–1 값 |
| `loudness_db_a` | 고정 torchcrepe 함수의 프레임별 A-weighted 음량(dB) |
| `hz` | 기존 필터 적용 결과. 점수 ≥0.21, 음량 ≥−60인 프레임의 `raw_hz`, 나머지는 0 |

`periodicity`는 보정된 확률이 아니며, `loudness_db_a < -60`은 해당 함수의 cutoff다.
이를 사람이 인지하는 무음·보컬 부재·정답 판정과 동일하게 취급하지 않는다. 분석 시각도
acoustic/perceptual onset 또는 확정 음표 경계가 아니다. `raw_hz`는 신경망 posterior
전체가 아니라 decoder 출력이다.

receipt의 `source_frames`와 `source_sample_rate=16000`은 **16kHz로 디코딩한 분석
오디오**를 가리킨다. 원본 컨테이너의 44.1kHz 프레임 수가 아니다. `hop=160`,
`pad=true`에서 `T = 1 + source_frames // 160`을 검증한다. 마지막 관측이 오디오
끝에 놓일 수 있다. 배열의 유한성·범위·길이·시각과 필터 결과의 byte 일치를 검사하며,
잘린 관측·다른 inventory·알 수 없는 버전은 명시적으로 거부한다.

원본 archive와 receipt는 기존 Song model evidence 경로로 해시를 검증해 보존하고,
Job 삭제 후에도 유지한다. 구조 reader는 archive 형식을 검증한다. 라이브 wrapper는
추가로 입력/출력·adapter 해시, 모델·설정·runtime 출처를 검증하며, 과거 자료를 읽는
호출자도 기존 evidence manifest의 무결성 검사를 거쳐야 한다.

## 버전 1과 호환 정책

버전 필드가 없거나 1인 과거 자료는 `times`, `hz` 두 배열로 읽는다. 없는 raw 배열은
`None`으로 반환하며 파일을 다시 쓰거나 0으로 채우지 않는다. 원래 F0·주기성·음량과
전체 분석 프레임 범위는 이 자료만으로 복원할 수 없다. 특히 `hz=0`에서 어떤 필터가
작동했는지, 모델 근거가 없었는지 구별할 수 없다. 버전을 올린 척하는 migration은 하지 않는다.

이 변경은 [#300](https://github.com/JDeun/audio-score-tool/issues/300)의 연속 관측 보존
부분이다. 경계/음표 가설·performed/written 대응 graph, 사용자 patch와 검수 UI의
전체 계약은 아직 구현 완료로 표시하지 않는다. 음표·옥타브를 자동 수정하지 않는다.

### 선택 음표의 원본 모델 가설 (선택적 v1)

새 고정 레시피 실행은 보컬 스템의 동일성을 두 모델 호출 전후에 확인하고, YourMT3 원본 MIDI와 런타임, 선택 MIDI, Tiny 프레임과 영수증의 해시를 비공개 사이드카에 연결한다. 과거 YourMT3 영수증에는 입출력 연결이 없으므로 기존 작업은 바이트가 같아도 소급하여 연결하지 않는다. 선언된 파일의 누락·손상은 최초 보존과 작업 정리를 막고, 크기 제한이나 지원되지 않는 이벤트 순서는 가설만 unavailable로 남긴다.

원본 후보는 모델이 출력한 구간이며 시작과 끝은 실제 음향 또는 지각 경계가 아니다. 음높이, 악기/타악기 및 템포를 적용한 MIDI 틱의 시작·끝이 정확하고 유일하게 일치할 때만 선택 이벤트와 동등하다고 표시한다. 중복은 ambiguous, 근거 부족은 unavailable이다. 이는 인과적 출처나 정답을 증명하지 않는다. API는 검증된 기존 계보 뒤에 각 출처의 후보와 Tiny 프레임 인덱스 범위를 부가하며 원본 배열을 공개하지 않는다. 프레임 시계는 스템 로컬이고 0.01초 간격이다. Tiny v2의 raw pitch, periodicity, A-weighted loudness는 보조 관측이며 periodicity는 보정된 발성 확률이 아니다. 빈 범위도 가능하다. 원본 오디오 탐색 위치와 악보 음높이·리듬은 이 관측으로 바뀌지 않는다. 분할·병합은 증명된 출처별 관측을 보존하며 알 수 없는 출처는 추측하지 않는다. 이 기능은 독립 정답이나 전체 음향/지각 가설 그래프 완성을 뜻하지 않는다.
