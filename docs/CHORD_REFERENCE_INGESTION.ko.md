# 오디오 없이 코드 정답 주석 가져오기 (#58)

Chordify의 CASD JAMS, Isophonics/빌보드의 텍스트 LAB, ChoCo 및 사용자 소유의 JAMS 등 **정당한 사용 권한이 있는** 코드 주석을 공통 다중-주석자 JSON으로 정규화합니다. 공식 사이트의 계정·결제·인증 우회, 무단 스크래핑, 원본 녹음 다운로드는 하지 않습니다.

`scripts/import_chord_reference.py`는 `--format jams` 또는 `--format lab`를 지원합니다. JAMS는 `namespace=chord`인 복수의 정답 주석자 데이터를 보존합니다. LAB는 `start_seconds end_seconds chord_symbol` 줄 단위이며, 여러 파일을 나열하면 각각 독립 주석자로 기록됩니다. 필수 원본 녹음 SHA-256 및 재생 시간은 운영자가 제공합니다.

```bash
uv run --frozen python scripts/import_chord_reference.py \
  /private/CASD/authorized-annotation.jams \
  --format jams --dataset casd --license CC-BY-NC-SA-4.0 \
  --rights-reviewed --recording-sha256 <ACTUAL_AUDIO_SHA256> \
  --duration-seconds 210.5 \
  --output /private/chord-references/song-reference.json

# Separate beat/downbeat reference CSV (time_seconds,kind) is optional:
uv run --frozen python scripts/import_chord_reference.py \
  /private/annotations/expert-a.lab /private/annotations/expert-b.lab \
  --format lab --dataset isophonics --license CC-BY-4.0 \
  --rights-reviewed --recording-sha256 <ACTUAL_AUDIO_SHA256> \
  --duration-seconds 210.5 --beats-csv /private/beat-grid.csv \
  --output /private/chord-references/experts.json
```

이 예시의 데이터와 라이선스는 **실제로 확인해야 합니다**. 라이선스를 잘못 기재하거나 소스별 이용약관이 검증되지 않았다면 실행해서는 안 됩니다. CASD는 CC-BY-NC-SA-4.0 사용을 명시해야 하고 상업 평가 모드에서는 차단됩니다. 다른 데이터셋의 조건도 개별 원출처에서 확인한 뒤에만 `--rights-reviewed`로 승인합니다.

변환 도구는 코드 간 빈 구간을 임의로 `N`으로 채우지 않습니다. 모든 독립 주석은 선언된 길이까지 간격·중복 없이 완전히 커버해야 합니다. `N`이나 `N.C.`는 **주석자가 명시한 경우에만** no-chord로 보존합니다. 입력 파일의 SHA-256, 주석자 수, 정규화 이벤트를 기록하고 원본 오디오·비공개 경로를 출력에 복사하지 않습니다. 마커의 화성 의미와 녹음 일치는 이 도구가 독립 검증하지 않습니다.

출력 JSON은 `scripts/score_casd_chords.py`와 `scripts/compare_chord_playalong.py`에서 요구하는 `annotators[{index,intervals[{start,end,label}]}]`, `recording_sha256`, `duration_seconds` 계약을 충족합니다. 정당하게 확보한 *실제* 녹음과 독립 주석의 정렬, 다수 곡 WCSR, beat F1 및 주석자 간 차이의 실측 인수는 계속 #58/#53/#34에 남습니다.
