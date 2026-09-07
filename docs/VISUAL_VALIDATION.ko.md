# OMR 시각 검증

AudioScoreTool v0.8의 OMR 검증은 **원본 악보와 인식 결과를 다시 렌더링한 악보를 시각적으로 비교**하는 보조 QA 경로를 제공합니다.

## 목적

Audiveris나 다른 OMR 엔진은 다음 오류를 만들 수 있습니다.

- 임시표 누락/추가
- 음표·쉼표 duration 오인식
- beam/tie/slur 혼동
- clef/key/time signature 오류
- repeat/ending 누락
- lyrics/text 위치 오류
- staff/part 누락 또는 중복

결정론적 MusicXML validator는 구조적 오류를 잘 찾지만, 원본 종이 악보와 다르게 읽힌 기호까지 모두 검출할 수는 없습니다. 시각 검증은 이 빈틈을 메우기 위한 **advisory critic**입니다.

## 처리 순서

```text
OMR 원본 PDF/Image
        ↓
managed asset 보존
        ↓
현재 canonical MusicXML ─→ LilyPond/MuseScore fallback ─→ PDF
        ↓                                             ↓
원본 rasterize                                  결과 rasterize
        └──────────── page pair ─────────────────────┘
                              ↓
                   Vision-capable LLM/VLM
                              ↓
           page / measure / category / confidence
                              ↓
                     사용자 검토 후보
```

## 안전 정책

- VLM 결과는 자동 수정에 사용하지 않습니다.
- `auto_edit=false`를 유지합니다.
- confidence가 낮으면 사용자에게 직접 대조하도록 안내합니다.
- 원본 증거가 없는 일반 AMT 곡에는 시각 OMR 검증을 실행하지 않습니다.
- 텍스트 LLM critic과 시각 critic은 서로 독립적입니다.

## 요구 도구

### 원본이 PDF인 경우

Poppler의 `pdftoppm`이 필요합니다.

macOS 예:

```bash
brew install poppler
```

### 재렌더링

우선순위:

1. LilyPond + `musicxml2ly`
2. MuseScore fallback

### Vision 모델

OpenAI-compatible `/chat/completions`에서 `image_url` content를 지원하는 모델을 연결합니다.

기본 입력 예시는 로컬 모델을 가정합니다.

```text
endpoint: http://127.0.0.1:11434/v1
vision model: qwen2.5vl:7b
```

모델명은 설치 환경에 맞게 바꿀 수 있습니다.

## 반환 이슈 형식

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

## 현재 범위

- 최대 8페이지를 rasterize할 수 있습니다.
- 실제 VLM 요청은 비용/컨텍스트 크기를 고려해 앞쪽 페이지 pair를 우선 비교합니다.
- 마디 번호는 vision model의 추정일 수 있으므로 최종 근거로 사용하지 않습니다.
- 향후에는 OSMD의 measure bounding box와 연결해 **페이지 좌표 → 정확한 MusicXML measure ID** 매핑을 추가하는 것이 권장됩니다.
