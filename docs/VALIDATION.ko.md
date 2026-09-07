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
검토 우선순위 / 의심 구간
        ↓
사용자 확인
```

## 왜 LLM을 정답 판정기로 쓰지 않나요?

MusicXML과 코드/가사 분석 결과만 본 LLM은 원음의 실제 acoustic evidence를 직접 측정하지 못합니다. 따라서 특정 음표가 원곡과 다르다고 확정하거나 자동으로 악보를 수정하게 하면 hallucination 위험이 큽니다.

LLM이 잘하는 것은 다음입니다.

- 박자/조성/화성 문맥에서 이상한 구간 찾기
- 악기 음역이나 역할상 의심스러운 구간 찾기
- 자동 코드와 음표 문맥의 불일치 후보 찾기
- 가사 정렬/표기상 이상 패턴 찾기
- 결정론적 검사 결과를 음악적으로 우선순위화하기
- 사람이 확인해야 할 구간을 짧은 목록으로 압축하기

LLM이 단독으로 하면 안 되는 것은 다음입니다.

- 원음을 듣지 않고 note correctness 확정
- 높은 confidence 근거 없이 pitch/rhythm 자동 수정
- 악기 배정을 임의로 바꾸기
- 사용자의 승인 없이 MusicXML 변경

## 1. 결정론적 검사

현재 구현은 다음을 검사합니다.

- 박자표 대비 단순 voice 마디 duration 불일치
- 일반적 악기 음역에서 크게 벗어난 pitch
- 쉼표에 잘못 연결된 lyric
- 중복 tie 표시
- 존재하지만 비어 있는 part

다성부 `backup/forward`가 있는 복잡한 마디는 단순 duration 합산으로 오탐할 수 있으므로 해당 duration 규칙은 보수적으로 적용합니다.

## 2. LLM critic

OpenAI-compatible Chat Completions endpoint를 사용합니다.

기본 예시:

```text
endpoint = http://127.0.0.1:11434/v1
model    = qwen3.5:9b
```

Ollama, vLLM, LM Studio 등 OpenAI-compatible API를 제공하는 로컬 서버를 연결할 수 있습니다. 원격 endpoint는 HTTPS만 허용합니다.

특정 provider의 structured-output 확장에 의존하지 않습니다. Prompt에서 JSON 응답을 요구하고 결과에서 JSON object를 추출하는 방식으로 구현해 Ollama/vLLM/LM Studio/hosted compatible API 간 호환성을 높였습니다.

API key 자체는 설정 파일에 저장하지 않습니다. 예를 들어 UI에 `OPENAI_API_KEY`라는 **환경변수 이름만** 저장하고 실제 token은 프로세스 환경에서 읽습니다.

LLM에는 다음만 전달합니다.

- 결정론적 검증 결과
- 파트/마디/음역 요약
- 자동 코드 분석 결과
- lyric alignment 결과
- bounded transcript sample

전체 원본 음원이나 임의 파일은 전송하지 않습니다.

## 3. OMR 원본 ↔ 재렌더링 Vision 비교

PDF/이미지 OMR 입력은 원본 악보를 `assets/<song-id>/original-score.*`로 보존합니다. 현재 MusicXML을 LilyPond 우선, MuseScore fallback으로 다시 렌더링한 뒤 원본 페이지와 인식 결과 페이지를 Vision-capable LLM/VLM에 쌍으로 전달합니다.

검토 대상:

- accidental 누락/추가
- clef / key / time signature
- note/rest duration
- beam / tie / slur
- repeat / ending
- lyrics / text / dynamics
- staff/part 누락 또는 중복

원본이 PDF이면 Poppler의 `pdftoppm`을 사용해 페이지를 PNG로 rasterize합니다. 이미지 입력은 Pillow로 정규화합니다.

기본 예시:

```text
vision model = qwen2.5vl:7b
max pages    = 4
```

반환 이슈 예:

```json
{
  "severity": "warning",
  "category": "accidental",
  "message": "원본에는 임시표가 있으나 재렌더링 결과에서 보이지 않습니다.",
  "page": 1,
  "measure": "12",
  "confidence": 0.88,
  "suggested_action": "12마디 해당 음의 alter 값을 확인하세요.",
  "source": "vision"
}
```

시각 검증의 마디 번호는 VLM 추정일 수 있으므로 참고용입니다. 장기적으로는 OSMD measure bounding box와 연결해 페이지 좌표를 정확한 MusicXML measure ID로 매핑하는 것이 목표입니다.

## 응답 정책

텍스트 LLM과 Vision 결과는 모두 advisory issue입니다.

```json
{
  "severity": "warning",
  "category": "harmony",
  "message": "M12의 코드 문맥이 인접 마디와 급격히 달라 검토가 필요합니다.",
  "part": "Piano",
  "measure": "12",
  "confidence": 0.71,
  "suggested_action": "원음 또는 베이스 파트를 확인하세요.",
  "source": "llm"
}
```

UI에서는 각각 `LLM 가설`, `원본 비교`로 구분해 표시합니다.

모든 validator는 `auto_edit=false`를 유지합니다.

## 4. 다음으로 가장 중요한 검증: audio evidence

OMR에는 원본 이미지라는 직접 증거가 있지만, AMT에는 원음 자체가 correctness의 핵심 증거입니다. 다음 단계는 **symbol ↔ audio evidence** 비교입니다.

권장 순서:

1. 현재 MusicXML/MIDI를 synthesize
2. 원음과 시간 정렬
3. frame/onset/chroma 또는 learned audio embedding 비교
4. discrepancy가 큰 구간 추출
5. 해당 구간만 LLM critic에 구조화된 evidence와 함께 전달

이렇게 하면 LLM이 임의로 오류를 상상하는 것이 아니라 실제 audio-symbol mismatch 후보를 설명하고 우선순위화할 수 있습니다.

장기적으로는 다음 score를 만들 수 있습니다.

```text
validation_score =
    structural_validity
  + symbolic_consistency
  + omr_visual_similarity
  + audio_resynthesis_similarity
  + ensemble_disagreement
  + LLM_review_priority
```

여기서 LLM은 **reasoning/triage layer**이고, acoustic correctness 또는 원본 OMR correctness의 1차 근거를 대체하지 않습니다.

## API

```text
GET  /api/validation/settings
PUT  /api/validation/settings
POST /api/songs/{song_id}/validate
GET  /api/songs/{song_id}/validation
```

`POST .../validate`는 항상 deterministic validation을 실행하고 설정 또는 요청에 따라 텍스트 LLM critic과 OMR Vision critic을 추가합니다.

검증 결과는 `song_analysis.validation_report`로 저장되며, 시각 OMR 결과는 `song_analysis.omr_visual_validation`에도 별도로 저장됩니다. 악보 자체는 변경하지 않습니다.
