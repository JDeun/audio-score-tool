# 악보 검증 설계

AudioScoreTool의 검증은 **LLM 단독 판정이 아니라 계층형 QA**로 설계합니다.

```text
MusicXML / 분석 결과
        ↓
1. 결정론적 규칙 검사          ← 항상 사용 가능
        ↓
2. 선택적 LLM critic           ← 기본 OFF
        ↓
3. OMR Vision 비교             ← 선택
        ↓
4. AMT Audio evidence          ← 선택, LLM 불필요
        ↓
검토 우선순위 / 의심 구간
        ↓
사용자 확인
```

모든 단계는 현재 `auto_edit=false`입니다.

## LLM은 필수가 아닙니다

AudioScoreTool은 로컬 LLM 설치를 요구하지 않습니다. LLM 기능을 전혀 사용하지 않아도 다음은 동작합니다.

- deterministic structural validation
- AMT 원음 ↔ 재합성 Audio evidence
- 악보 편집/Revision/Export

`GET /api/validation/settings`는 `llm_required=false`를 반환하며 LLM critic 기본값은 OFF입니다.

LLM을 켰다가 endpoint 장애, 인증 실패, 모델 미설치 등이 발생해도 전체 검증 요청을 실패시키지 않습니다. 해당 단계만 `llm_skipped` 사유를 남기고 나머지 검증 결과를 정상 반환합니다.

## LLM/API 연결 방식

LLM/Vision은 OpenAI-compatible Chat Completions API transport를 사용합니다.

따라서 두 방식 모두 지원합니다.

### 로컬

```text
Ollama / vLLM / LM Studio
http://127.0.0.1:11434/v1
```

### 원격 API

```text
https://provider.example.com/v1
```

원격 endpoint는 HTTPS만 허용합니다. 모델명과 endpoint는 UI에서 지정합니다. API key 값 자체는 settings 파일에 저장하지 않고 환경변수 이름만 저장합니다.

예:

```text
endpoint    = https://api.example.com/v1
model       = provider/model-name
api_key_env = OPENAI_API_KEY
```

즉 사용자는 로컬 모델 없이 hosted API만 연결해서 LLM/Vision critic을 사용할 수도 있고, AI critic 전체를 끄고 deterministic/audio-evidence 검증만 사용할 수도 있습니다.

## 1. 결정론적 검사

현재 구현은 다음을 검사합니다.

- 박자표 대비 단순 voice 마디 duration 불일치
- 일반적 악기 음역에서 크게 벗어난 pitch
- 쉼표에 잘못 연결된 lyric
- 중복 tie 표시
- 존재하지만 비어 있는 part

다성부 `backup/forward`가 있는 복잡한 마디는 단순 duration 합산으로 오탐할 수 있으므로 해당 duration 규칙은 보수적으로 적용합니다.

## 2. 선택적 LLM critic

LLM에는 결정론적 검증 결과, 파트/마디/음역 요약, 자동 코드, lyric alignment, bounded transcript sample만 전달합니다.

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

Vision도 선택 기능이며 endpoint가 없으면 건너뜁니다. 결과는 `song_analysis.omr_visual_validation`에도 저장합니다.

## 4. 원음 ↔ 현재 악보 재합성 Audio evidence

AMT 입력은 채보 시 원본 음원을 `assets/<song-id>/original-audio.*`로 별도 보존합니다. 따라서 Job workspace를 정리해도 현재 악보와 원음의 비교 근거를 유지할 수 있습니다.

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

이 단계에는 LLM/API가 필요하지 않습니다.

### 필요한 도구

- `music21`: MusicXML → MIDI
- `FluidSynth`: MIDI → WAV
- `ffmpeg`: 원본/합성 WAV 정규화
- General MIDI 호환 SoundFont (`.sf2` / `.sf3`)

SoundFont는 라이선스 조건이 다양하므로 앱에 번들하지 않습니다.

환경변수 예시:

```text
AST_FFMPEG_CMD=ffmpeg
AST_FLUIDSYNTH_CMD=fluidsynth
AST_VALIDATION_SOUNDFONT=/path/to/general-midi.sf2
```

## 5. 검증 역할 분리

```text
Deterministic   구조적 불가능/이상
Text LLM        선택적 reasoning / triage
Vision          선택적 OMR 원본 이미지 비교
Audio-symbol    AMT 원음 직접 증거, LLM 불필요
Human           최종 판단 및 수정
```

## API

```text
GET  /api/validation/settings
PUT  /api/validation/settings
POST /api/songs/{song_id}/validate
GET  /api/songs/{song_id}/validation
```

`POST .../validate`는 항상 deterministic validation을 실행하고 요청/설정에 따라 LLM, Vision, Audio evidence를 추가합니다. 검증 결과는 `song_analysis.validation_report`에 저장되고 악보 자체는 변경하지 않습니다.
