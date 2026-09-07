# 악보 검증 설계

AudioScoreTool의 검증은 **LLM 단독 판정이 아니라 계층형 QA**로 설계합니다.

```text
MusicXML / 분석 결과
        ↓
1. 결정론적 규칙 검사
        ↓
2. 선택적 LLM critic
        ↓
3. OMR이면 원본↔재렌더링 Vision 비교
        ↓
4. AMT이면 원음↔현재 악보 재합성 Audio evidence
        ↓
검토 우선순위 / 의심 구간
        ↓
사용자 확인
```

모든 단계는 현재 `auto_edit=false`입니다.

## 1. 결정론적 검사

현재 구현은 다음을 검사합니다.

- 박자표 대비 단순 voice 마디 duration 불일치
- 일반적 악기 음역에서 크게 벗어난 pitch
- 쉼표에 잘못 연결된 lyric
- 중복 tie 표시
- 존재하지만 비어 있는 part

다성부 `backup/forward`가 있는 복잡한 마디는 단순 duration 합산으로 오탐할 수 있으므로 해당 duration 규칙은 보수적으로 적용합니다.

## 2. LLM critic

OpenAI-compatible Chat Completions endpoint를 사용합니다. LLM에는 결정론적 검증 결과, 파트/마디/음역 요약, 자동 코드, lyric alignment, bounded transcript sample만 전달합니다.

LLM은 원음을 직접 측정하지 않으므로 note correctness의 정답 판정기로 사용하지 않습니다. UI에서는 `LLM 가설`로 표시합니다.

## 3. OMR 원본 ↔ 재렌더링 Vision 비교

PDF/이미지 OMR 입력은 원본 악보를 `assets/<song-id>/original-score.*`로 보존합니다. 현재 MusicXML을 다시 렌더링한 뒤 원본 페이지와 결과 페이지를 Vision-capable 모델에 쌍으로 전달합니다.

검토 대상:

- accidental 누락/추가
- clef / key / time signature
- note/rest duration
- beam / tie / slur
- repeat / ending
- lyrics / text / dynamics
- staff/part 누락 또는 중복

결과는 `song_analysis.omr_visual_validation`에도 저장합니다.

## 4. 원음 ↔ 현재 악보 재합성 Audio evidence

AMT 입력은 채보 시 원본 음원을 `assets/<song-id>/original-audio.*`로 별도 보존합니다. 따라서 Job workspace를 정리해도 현재 악보와 원음의 비교 근거를 유지할 수 있습니다.

검증 파이프라인:

```text
현재 MusicXML
    ↓ music21
현재 MIDI
    ↓ FluidSynth + 사용자 SoundFont
재합성 WAV

원본 음원
    ↓ ffmpeg
정규화 WAV

두 WAV
    ↓
chroma 추출 + onset/novelty 기반 global alignment
    ↓
시간창별 chroma cosine similarity
    ↓
저유사도 구간 → 검토 후보
```

### 왜 waveform similarity를 쓰지 않나요?

원곡과 SoundFont 합성음은 음색, 믹싱, 잔향, dynamics가 크게 다릅니다. raw waveform이나 일반 스펙트럼을 직접 비교하면 악보가 맞아도 낮은 유사도가 나올 수 있습니다.

현재 v1은 12차원 chroma를 사용해 음색 영향을 줄이고 pitch-class/화성 구조 차이에 집중합니다. onset novelty는 두 신호의 global time shift를 추정하는 데 사용합니다.

### 필요한 도구

- `music21`: MusicXML → MIDI
- `FluidSynth`: MIDI → WAV
- `ffmpeg`: 원본/합성 WAV 정규화
- General MIDI 호환 SoundFont (`.sf2` / `.sf3`)

SoundFont는 라이선스 조건이 매우 다양하므로 앱에 번들하지 않습니다. 사용자가 직접 경로를 지정합니다.

환경변수 예시:

```text
AST_FFMPEG_CMD=ffmpeg
AST_FLUIDSYNTH_CMD=fluidsynth
AST_VALIDATION_SOUNDFONT=/path/to/general-midi.sf2
```

UI의 악보 검증 창에서도 세 경로를 지정할 수 있습니다.

### 결과 예

```json
{
  "severity": "warning",
  "category": "audio-symbol discrepancy",
  "message": "원음과 현재 악보 재합성의 chroma 유사도가 낮습니다 (0.31).",
  "start_seconds": 42.5,
  "end_seconds": 45.0,
  "measure": "22",
  "confidence": 0.81,
  "suggested_action": "해당 시간대의 누락/과잉 음표, 옥타브, 코드 또는 파트 배정을 원음과 대조하세요.",
  "source": "audio_symbol"
}
```

마디 번호는 현재 첫 tempo/time signature를 이용한 보수적 추정입니다. 변박/tempo map이 복잡한 곡에서는 시간 범위가 1차 근거이며 마디 번호는 참고값입니다.

결과는 `song_analysis.audio_symbol_validation`에도 저장합니다.

## 5. 검증 역할 분리

```text
Deterministic   구조적 불가능/이상
Text LLM        음악적 reasoning / triage
Vision          OMR 원본 이미지 직접 증거
Audio-symbol    AMT 원음 직접 증거
Human           최종 판단 및 수정
```

LLM이나 Vision 모델이 자동으로 MusicXML을 바꾸지 않습니다. Audio evidence 역시 low-similarity 구간을 오류로 확정하는 것이 아니라 **직접 원본 근거가 있는 검토 우선순위**로 취급합니다.

## 6. 향후 개선

현재 audio-symbol v1은 다음을 더 발전시킬 수 있습니다.

- MusicXML tempo map을 완전히 해석한 정확한 초↔마디 매핑
- part/stem별 비교
- CQT 기반 onset/pitch feature
- learned music-audio embedding
- MuScriptor / YourMT3 / MR-MT3 ensemble disagreement
- discrepancy가 큰 구간만 LLM에 구조화된 evidence로 전달

장기 점수 예:

```text
validation_score =
    structural_validity
  + symbolic_consistency
  + omr_visual_similarity
  + audio_resynthesis_similarity
  + ensemble_disagreement
  + LLM_review_priority
```

## API

```text
GET  /api/validation/settings
PUT  /api/validation/settings
POST /api/songs/{song_id}/validate
GET  /api/songs/{song_id}/validation
```

`POST .../validate`는 항상 deterministic validation을 실행하고 설정에 따라 LLM, Vision, Audio evidence를 추가합니다. 검증 결과는 `song_analysis.validation_report`에 저장되고 악보 자체는 변경하지 않습니다.
