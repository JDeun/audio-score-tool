# Tier 2 Real-Music Benchmark

이 디렉터리는 실제 음악 기반 v1 품질 acceptance의 **manifest/reference/result contract**만 저장합니다. 저작권이 있는 원본 음원은 저장소에 커밋하지 않습니다.

## 입력

각 corpus item은 `manifest.json`에 다음을 기록합니다.

- stable case id
- category / genre / structure tags
- private/local audio locator
- reference MIDI/MusicXML locator
- license/ownership note
- expected meter / pickup / part metadata

`manifest.example.json`은 형식 예시입니다.

## 출력

각 엔진 실행은 machine-readable JSON result를 남겨야 합니다.

필수 모델 지표:

- note precision / recall / F1
- onset MAE / offset MAE
- instrument-aware F1
- meter / pickup / first-downbeat
- chord / lyrics / SATB metrics where applicable

필수 제품 지표:

- manual note/chord/measure/part/lyric/layout edits
- total edit actions
- time to publish
- successful export

## 원칙

1. 실제 audio는 Git에 넣지 않습니다.
2. 같은 manifest/reference로 candidate engine을 비교합니다.
3. engine revision, runtime revision, checksum을 결과에 기록합니다.
4. 사람이 수정한 양과 publish time이 최상위 제품 KPI입니다.
5. Tier 2 결과 없이 commercial default engine을 교체하지 않습니다.
