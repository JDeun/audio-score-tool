# MIDI와 MusicXML의 음표 보존

이 문서는 [#184](https://github.com/JDeun/audio-score-tool/issues/184)의 **예측 MIDI → 악보 → 재생 MIDI** 손실을 다룹니다. 모델이 어떤 음을 예측하는지와 이미 예측한 음을 변환 중 보존하는지는 서로 다른 검증 대상입니다. 합성 회귀 테스트의 성공을 실제 다장르 채보 정확도나 상용 출시 승인으로 해석하지 않습니다.

## 변환 경로

`notation_backend.midi_to_musicxml()`은 원본 MIDI의 정수 tick을 읽어 `midi_score_import.py`에서 MusicXML을 만듭니다.

- onset과 offset이 모두 같은 서로 다른 음높이만 한 화음으로 묶습니다. 가까이 시작한 아르페지오를 임의로 동시 화음으로 합치지 않습니다.
- 길이가 다른 겹친 음은 안정적인 voice로 분리하고, 마디 경계를 넘는 음은 같은 voice의 tie로 기록합니다.
- 원본 track·GM 프로그램·드럼 구분별 파트를 유지하며, 같은 조합 안에서 서로 다른 채널의 음이 시간상 겹치지 않는 순차 채널 재사용만 한 파트로 합칩니다. 채널 간 동시 연주가 있으면 채널별 파트를 유지하고, 드럼은 각 음의 percussion instrument 바인딩을 구분합니다.
- 템포·박자·조성 변경과 대응 가능한 MIDI 가사 이벤트를 기록합니다.
- 일반 음가로 정확히 표현되지 않는 연주 길이는 수치 duration을 유지합니다. 읽기 좋은 리듬으로 정리하는 quantization은 별도 편집 단계이며, 보존을 검증하기 위해 음표를 추가하지 않습니다.

`notation_backend.musicxml_to_midi()`는 music21로 악보를 해석한 뒤 `midi_ties.py`에서 part/voice/pitch가 같고 시간상 이어지는 tie만 병합합니다. MusicXML에 적힌 GM과 드럼별 instrument를 복구하고, `midi_channels.py`는 많은 악기가 순차적으로 사용될 때 프로그램이 충돌하지 않게 MIDI 채널을 재배치합니다. 이 과정에서 canonical MusicXML을 다시 쓰지 않습니다.

선택 파트 합본도 MusicXML tree를 직접 추출합니다. 파트 제거를 위해 전체 악보를 music21로 다시 직렬화하지 않으며, 첫 파트에만 있는 템포를 선택된 첫 파트에 전달합니다. 사용자 흐름은 [편집기 문서](EDITOR.ko.md)의 선택 파트 출력 절차를 따릅니다.

## 회귀 검증

`tests/test_midi_musicxml_fidelity.py`는 직접 만든 원본 MIDI를 실제 변환 함수에 통과시켜 음높이·시작·끝·GM 프로그램·드럼 종류를 비교합니다. 주요 사례는 다음과 같습니다.

- 빠른 아르페지오와 같은 pitch의 겹침
- 마디를 넘는 polyphony와 여러 voice의 tie
- 일반 음가에 맞지 않는 tick 길이
- 템포 변경과 3/4 → 5/8 박자 변경
- GM 프로그램의 명시적 보존과 순차적인 채널 재사용
- 같은 드럼 파트의 킥·스네어·하이햇
- 실제 PDF 생성과 편집·Undo·최종 출력 경로

변환 코드가 바뀌는 PR은 기존 **CocoChorales Original Reference MusicXML Roundtrip Control** 및 **CocoChorales Paired MR-MT3 vs YourMT3** workflow에도 연결됩니다. 두 workflow는 고정한 동일 저자 제공 원본 4쌍으로 정답 MIDI 자체의 변환 대조군과 모델 예측 MIDI/엔진이 만든 MusicXML의 평가를 나눕니다. 원본 음원·정답 MIDI·예측 MIDI/XML·체크포인트는 공개 artifact로 올리지 않고 통계와 출처 메타데이터만 남깁니다.

이 4곡은 기존에 기록된 **train split 진단 자료**입니다. 결과가 개선되어도 held-out 장르별 평가, 사람의 수정량·출판 시간, PDF 조판 품질과 지원 OS의 실제 동작은 [v1 준비 기준](V1_READINESS.ko.md)에 따라 별도 검증합니다.

## 실제 PR #194 변환 검증 결과 — 2026-11-09

[PR #194](https://github.com/JDeun/audio-score-tool/pull/194)의 최종 코드 `acf251750d1409ec178a45928d8c952e2352cade`에서 실행한 [paired run 42580255321](https://github.com/JDeun/audio-score-tool/actions/runs/42580255321)과 [reference control run 42580255193](https://github.com/JDeun/audio-score-tool/actions/runs/42580255193)은 모두 성공했습니다. 각 실행은 저자가 공개한 원본 CocoChorales 음원·정답 MIDI 4쌍을 검증하며, paired 실행은 두 모델을 같은 원본 SHA와 정답에 대조합니다.

다음은 4곡을 동일 가중치로 평균한 F1입니다. 모델 예측의 보존 여부는 **그 모델의 원래 예측 MIDI**를 기준으로 따로 측정했습니다.

| 변환 대상 → MusicXML → 재생 MIDI | 비교 기준 | onset F1 | onset+offset F1 | GM 포함 onset+offset F1 |
| --- | --- | ---: | ---: | ---: |
| MR-MT3 예측 | 같은 MR-MT3 예측 MIDI | 1.0 | 1.0 | 1.0 |
| YourMT3+ 예측 | 같은 YourMT3+ 예측 MIDI | 1.0 | 1.0 | 1.0 |
| 원본 정답 MIDI | 같은 원본 정답 MIDI | 1.0 | 1.0 | 1.0 |

근거는 [paired comparison job 129038786360](https://github.com/JDeun/audio-score-tool/actions/runs/42580255321/job/129038786360)의 `musicxml_score_metrics`와 [reference control job 129037017984](https://github.com/JDeun/audio-score-tool/actions/runs/42580255193/job/129037017984)의 `reference_roundtrip_macro`입니다. 비교 허용오차는 onset 50 ms, offset은 50 ms와 정답 음 길이의 20% 중 큰 값이며, 악기 지표는 GM 프로그램과 드럼 구분까지 요구합니다. 이 결과는 **해당 비교 기준과 허용오차 안에서의 음표 보존**이며 바이트 단위 동일성이나 무한한 시간 해상도를 뜻하지 않습니다.

최종 MusicXML을 원본 정답에 비교한 값도 각 모델의 raw MIDI 정확도와 같았습니다.

| 엔진 | MusicXML 대 정답 onset F1 | onset+offset F1 | GM 포함 onset+offset F1 |
| --- | ---: | ---: | ---: |
| MR-MT3 | 0.65212963 | 0.43914280 | 0.22716306 |
| YourMT3+ | 0.83441140 | 0.67410101 | 0.04375000 |

따라서 이 실행에서는 변환이 이미 예측된 음표의 평가 점수를 추가로 낮추지 않았습니다. 모델의 잘못된 음표·악기 예측까지 교정됐다는 의미는 아닙니다. 4곡은 합성 합주 음원인 **CocoChorales train split**의 저자 제공 샘플이며, held-out 곡이나 실제 대중음악으로 일반화하는 근거가 아닙니다.

이 workflow는 `generate_tier2_predictions()`가 호출한 **엔진 직후의 MIDI와 MusicXML**을 측정합니다. `pipeline_v2`의 합창·가사 등 후처리, 편집기 조작, 최종 PDF·파트 출판까지 포함한 전체 제품 검증은 아닙니다. 아래 합창 정책의 회귀 검증도 이 실제 모델 실행과 구분합니다.

## 기본 채보와 명시적 합창 후처리

일반 full 채보의 `pipeline_v2.transcribe()`는 `choir_mode="off"`가 기본입니다. 악기 파트가 4개이거나 화음이 많다는 이유로 SATB로 재해석하지 않습니다. `auto`도 기존 Soprano/Alto/Tenor/Bass 표기를 확인할 뿐 원래 악보를 바꾸지 않습니다.

`choir_mode="choir"`를 명시한 경우에만 SATB 후보를 만듭니다.

- 음높이가 있는 기존 4개 파트는 음역에 따라 SATB 이름을 지정합니다. 음표를 music21로 다시 쓰지 않고 MusicXML의 파트 이름만 바꾸므로 원래 tick 기반 duration과 악기 바인딩을 유지합니다. 중앙 음높이가 같은 파트도 기존 순서대로 안정적으로 처리합니다.
- 단일 화음 파트는 지원 가능한 경우에만 4성부로 나눕니다. 중첩 Voice, 한 화음의 5음 이상 또는 중복된 동일 음높이는 임의로 줄이지 않고 원본을 유지합니다. 명시적인 합창 요청도 악기 프로그램을 Vocalist 등으로 자동 교체하는 근거로 사용하지 않습니다.
- 후보는 임시 파일에 저장한 뒤 원본과 같은 MusicXML→MIDI 변환기로 비교합니다. 중복을 포함한 재생 음표 수, 음높이, onset/offset, GM 프로그램, 드럼 구분과 템포 맵이 유지된 경우만 최종 경로로 옮깁니다. onset/offset 허용차는 부동소수점 누적 오차를 위한 1 μs이며, 위 연구용 F1의 50 ms 기준을 사용하지 않습니다. 비교 자체는 공통 MIDI 출력 해상도에서 이루어집니다.
- 음표 손실, 빈 후보, 보존 검증 실패나 예외가 있으면 합창 후보를 채택하지 않습니다. pipeline은 원본 악보로 완료하고 경고와 구조 보고서에 이유를 남깁니다.

`tests/test_choir_postprocess.py`와 `tests/test_pipeline_choir_fidelity.py`는 일반 기악 입력의 auto 비변형, 기존 60음이 48음 또는 0음으로 줄던 입력의 보존, 임의 tick, 같은 중앙 음높이, GM 변형 프로그램과 템포 변경, 후보의 잘못된 음높이·길이·악기 및 쓰기 예외를 확인합니다. 이 검사는 음표를 새로 추가하거나 실제 모델의 채보 정확도를 보정하지 않습니다. 모든 MIDI controller·페달·다이내믹 표현이 동일하다는 보장도 포함하지 않습니다.

## 지원 범위

현재 입력 계약은 metrical MIDI type 0/1의 양수 길이·정상 종료된 note 이벤트입니다. 독립 시간축의 type 2, SMPTE 시간축, 0 길이 또는 종료되지 않은 음표는 오류를 반환합니다.

피치벤드, CC, sustain pedal의 음향적 효과를 악보 음표로 해석하는 기능은 포함하지 않습니다. MIDI 출력에는 codec의 유한 tick 해상도가 있으며 그보다 짧은 길이를 잘못된 장음이나 미종결 이벤트로 성공 처리해서는 안 됩니다. 채널 충돌과 표현 제어를 동시에 안전하게 보존할 수 없는 경우도 명시적으로 실패합니다. 렌더러가 비정형 duration을 어떻게 표시하는지는 실제 조판 검토가 필요합니다.
