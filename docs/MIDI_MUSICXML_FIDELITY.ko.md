# MIDI와 MusicXML의 음표 보존

이 문서는 [#184](https://github.com/JDeun/audio-score-tool/issues/184)의 **예측 MIDI → 악보 → 재생 MIDI** 손실을 다룹니다. 모델이 어떤 음을 예측하는지와 이미 예측한 음을 변환 중 보존하는지는 서로 다른 검증 대상입니다. 합성 회귀 테스트의 성공을 실제 다장르 채보 정확도나 상용 출시 승인으로 해석하지 않습니다.

## 변환 경로

`notation_backend.midi_to_musicxml()`은 원본 MIDI의 정수 tick을 읽어 `midi_score_import.py`에서 MusicXML을 만듭니다.

- onset과 offset이 모두 같은 서로 다른 음높이만 한 화음으로 묶습니다. 가까이 시작한 아르페지오를 임의로 동시 화음으로 합치지 않습니다.
- 길이가 다른 겹친 음은 안정적인 voice로 분리하고, 마디 경계를 넘는 음은 같은 voice의 tie로 기록합니다.
- track/channel/program 조합별 파트와 명시적인 GM 프로그램을 유지합니다. 드럼은 각 음의 percussion instrument 바인딩을 구분합니다.
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

변환 코드가 바뀌는 PR은 기존 **CocoChorales Original Reference MusicXML Roundtrip Control** 및 **CocoChorales Paired MR-MT3 vs YourMT3** workflow에도 연결됩니다. 두 workflow는 고정한 동일 저자 제공 원본 4쌍으로 정답 MIDI 자체의 변환 대조군과 모델 예측 MIDI/최종 XML의 평가를 나눕니다. 원본 음원·정답 MIDI·예측 MIDI/XML·체크포인트는 공개 artifact로 올리지 않고 통계와 출처 메타데이터만 남깁니다.

이 4곡은 기존에 기록된 **train split 진단 자료**입니다. 결과가 개선되어도 held-out 장르별 평가, 사람의 수정량·출판 시간, PDF 조판 품질과 지원 OS의 실제 동작은 [v1 준비 기준](V1_READINESS.ko.md)에 따라 별도 검증합니다.

## 지원 범위

현재 입력 계약은 metrical MIDI type 0/1의 양수 길이·정상 종료된 note 이벤트입니다. 독립 시간축의 type 2, SMPTE 시간축, 0 길이 또는 종료되지 않은 음표는 오류를 반환합니다.

피치벤드, CC, sustain pedal의 음향적 효과를 악보 음표로 해석하는 기능은 포함하지 않습니다. MIDI 출력에는 codec의 유한 tick 해상도가 있으며 그보다 짧은 길이를 잘못된 장음이나 미종결 이벤트로 성공 처리해서는 안 됩니다. 채널 충돌과 표현 제어를 동시에 안전하게 보존할 수 없는 경우도 명시적으로 실패합니다. 렌더러가 비정형 duration을 어떻게 표시하는지는 실제 조판 검토가 필요합니다.
