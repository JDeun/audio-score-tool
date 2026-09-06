# 모델 Benchmark 가이드

## 목적

AudioScoreTool의 기본 preset은 하드웨어 종류에 따라 보수적으로 선택하지만, 실제 최적 조합은 음원 특성과 사용자 컴퓨터에 따라 달라집니다.

따라서 같은 음원을 여러 모델 조합으로 실행해 품질·속도·자원 사용을 직접 비교할 수 있도록 Benchmark 기능을 제공합니다.

## 프로필

### `score`

MuScriptor만 비교합니다.

- small
- medium
- large

가사 처리는 비활성화해 악보 모델 자체를 비교합니다.

### `lyrics`

가사 포함 조합을 비교합니다.

- balanced: MuScriptor medium + WhisperX small
- lyrics-medium: MuScriptor medium + WhisperX medium
- quality: MuScriptor large + WhisperX large-v3

### `all`

위 두 matrix를 모두 실행합니다.

## 기본 기록 지표

Reference가 없어도 다음을 기록합니다.

- config
- MuScriptor model
- WhisperX model
- wall-clock seconds
- success / failure
- lyric attachment ratio

## Ground Truth MIDI가 있을 때

다음 note-level 지표가 추가됩니다.

### Note Precision

예측한 note 중 reference와 pitch/onset tolerance 안에서 일치한 비율입니다.

### Note Recall

reference note 중 예측이 성공한 비율입니다.

### Note F1

Precision과 Recall의 조화평균입니다.

### Onset MAE

매칭된 note onset 시간의 평균 절대 오차를 ms 단위로 계산합니다.

현재 기본 onset tolerance는 50ms입니다.

## 실행

### 데스크탑

`성능 비교` 메뉴에서:

1. 테스트 음원 선택
2. 선택적으로 Ground Truth MIDI 추가
3. 비교 범위 선택
4. 실행
5. JSON / CSV 결과 확인

### CLI

```bash
uv run audio-score benchmark song.wav \
  --language ko \
  --profile all \
  --reference-midi reference.mid
```

## 결과

```text
benchmark-results/
├── benchmark.json
└── benchmark.csv
```

## 해석 권장 순서

1. `note_f1`이 충분히 높은 조합을 우선 선택
2. 비슷한 품질이라면 처리 시간이 짧은 조합 선택
3. 가사가 중요한 곡은 lyric attachment / 실제 가사 품질 별도 확인
4. Dense band / solo vocal / piano ballad 등 대표 음원 여러 종류로 반복

하나의 곡만으로 전역 preset을 결정하지 않는 것을 권장합니다.

## 현재 한계

자동 지표는 실제 상용 악보로서의 가독성, 코드 심벌의 음악적 타당성, 가사 syllable placement의 자연스러움까지 완전히 평가하지 못합니다.

최종 preset은 정량 지표와 실제 악보 검토를 함께 사용해 결정해야 합니다.
