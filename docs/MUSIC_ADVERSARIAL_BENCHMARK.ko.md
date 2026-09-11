# Music Adversarial Benchmark

AudioScoreTool의 일반 단위 테스트와 별도로, 음악적으로 까다로운 입력에서 구조 분석이 얼마나 안정적인지 수치화하는 품질 게이트입니다.

## Tier 1 — deterministic synthetic corpus

CI에서 항상 실행됩니다. 외부 모델 다운로드나 저작권 음원이 필요하지 않습니다.

현재 범위:

- **Music start**
  - 음악이 즉시 시작되는 입력에서 false trim 방지
  - 5초 무음 뒤 음악 시작
  - speech-like 비음악 intro 뒤 음악 시작에서 보수적 fail-safe
- **Meter / pickup**
  - 4/4 정박 시작
  - 4/4 1박 못갖춘마디
  - 3/4 정박 시작
  - 3/4 1/8음표 계열의 짧은 pickup
- **Choir / SATB**
  - 이미 4개 성부인 악보의 S/A/T/B 음역 정렬
  - 단일 chordal part의 보수적 SATB 분할
  - monophonic source에서 SATB를 날조하지 않는 fail-open

실행:

```bash
uv run --frozen python scripts/run_music_adversarial_benchmark.py
uv run --frozen python scripts/run_music_adversarial_benchmark.py --json
uv run --frozen python scripts/run_music_adversarial_benchmark.py --output /tmp/music-adversarial.json
```

기본 release threshold:

| Category | Minimum |
| --- | ---: |
| music_start | 0.75 |
| meter_pickup | 0.80 |
| choir | 0.80 |
| overall | 0.82 |

각 개별 case도 반드시 pass해야 하므로 평균 점수만으로 특정 실패를 숨길 수 없습니다.

## Tier 2 — owned/licensed real-music corpus

실제 AMT 품질 검증은 합성 fixture만으로 충분하지 않습니다. 실제 음원은 사용자가 소유하거나 benchmark 사용 허가가 명확해야 하며, 저장소에는 저작권 음원을 커밋하지 않습니다. 파일은 로컬/CI private artifact storage에서 공급하고, 저장소에는 corpus manifest, reference MIDI/MusicXML, 기대 구조 metadata와 metric schema만 둡니다.

### 권장 최소 corpus

장르/편성:

1. piano solo
2. acoustic guitar
3. pop/ballad
4. rock/full band
5. hip-hop/R&B
6. orchestral/ensemble
7. 무반주 SATB
8. SATB + piano
9. live/noisy recording

구조적 난제:

10. 10–30초 대사 또는 비음악 intro 후 곡 시작
11. 효과음/환경음 후 곡 시작
12. fade-in
13. 4/4 1박 pickup
14. 4/4 2박 pickup
15. 3/4 pickup
16. 박자표 변경
17. tempo change / rubato
18. unison → 2성 → 4성 변화
19. 남녀 음역 교차가 많은 합창
20. 박수/대화/ambient noise가 포함된 live recording

### 모델/음악 구조 지표

- music-start absolute error (seconds)
- first-downbeat error (seconds)
- meter accuracy
- pickup-length MAE (quarter lengths)
- note onset precision / recall / F1
- onset MAE
- note offset MAE
- instrument-aware precision / recall / F1
- chord accuracy
- lyrics alignment coverage
- SATB part-count accuracy
- SATB voice-range/order accuracy
- false-SATB rate on monophonic/non-choir inputs

### 제품 품질 지표

AudioScoreTool의 최종 목적은 benchmark score가 아니라 **사람이 얼마나 적게 고쳐서 출판 가능한 악보를 얻는지**입니다. 따라서 Tier 2 release report는 다음 필드를 함께 기록합니다.

- `manual_note_edits`
- `manual_chord_edits`
- `manual_measure_edits`
- `manual_part_edits`
- `manual_lyric_edits`
- `manual_layout_edits`
- `total_edit_actions`
- `time_to_publish_seconds`
- `successful_export`

가장 중요한 제품 KPI는 `time_to_publish_seconds`와 `total_edit_actions`입니다. note F1이 높더라도 최종 악보 수정 시간이 증가하면 제품 관점에서는 개선으로 간주하지 않습니다.

### 엔진 비교 규칙

동일한 corpus/reference와 동일한 후처리 정책으로 candidate engine을 비교합니다. commercial baseline은 다음 조건을 모두 만족해야 합니다.

1. 상업 사용 및 배포 provenance를 release 단위로 고정할 수 있음
2. mixed-audio polyphonic multi-instrument transcription 지원
3. Tier 2에서 최저 수준의 human correction cost를 달성
4. 지원 hardware에서 runtime/peak resource acceptance 충족
5. model/runtime revision과 checksum 고정 가능

MuScriptor public weights는 CC BY-NC 제한 때문에 commercial baseline 선정에서는 제외하며 개인/비상업 품질 비교에만 사용합니다.

## Release gate

Tier 1은 코드 회귀를 막는 필수 CI gate입니다.

Tier 2는 다음 시점에 필수입니다.

- 기본 AMT engine/revision 변경
- post-processing 구조 알고리즘의 release-critical 변경
- `1.0.0-rc.N` 생성
- stable release 승격

Tier 2 결과가 없는 모델 변경은 기본 엔진 승격 근거로 사용하지 않습니다.
