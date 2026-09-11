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

실제 AMT 품질 검증은 합성 fixture만으로 충분하지 않습니다. 아래 유형을 사용자가 소유하거나 benchmark 사용 허가가 명확한 음원으로 관리합니다.

권장 최소 corpus:

1. MV: 10–30초 대사 후 곡 시작
2. MV: 효과음/환경음 후 곡 시작
3. fade-in 곡
4. 4/4 1박 pickup
5. 4/4 2박 pickup
6. 3/4 pickup
7. 박자표 변경 곡
8. 무반주 SATB
9. SATB + 피아노
10. unison → 2성 → 4성 변화
11. 남녀 음역 교차가 많은 합창
12. live recording: 박수/대화/ambient noise 포함

실제 corpus는 저장소에 저작권 음원을 커밋하지 않습니다. 파일은 로컬/CI private artifact storage에서 공급하고, reference MIDI/MusicXML과 기대 구조 metadata만 별도 관리합니다.

평가 대상:

- music-start absolute error (seconds)
- first-downbeat error (seconds)
- meter accuracy
- pickup-length MAE (quarter lengths)
- note F1 / onset MAE / offset MAE
- SATB part-count accuracy
- SATB voice-range/order accuracy
- false-SATB rate on monophonic/non-choir inputs

Tier 1은 코드 회귀를 막는 필수 CI gate이고, Tier 2는 모델/엔진 버전 변경과 정식 release candidate에서 수행하는 음악 품질 acceptance입니다.
