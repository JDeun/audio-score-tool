# PDF / 이미지 악보 OMR

## 목적

AudioScoreTool은 음원만 입력으로 받지 않습니다. 기존 PDF/스캔 악보가 있다면 이를 다시 음원에서 채보하지 않고 OMR(Optical Music Recognition)로 MusicXML로 변환하여 동일한 편집·검증·출판 파이프라인에 넣습니다.

```text
PDF / PNG / JPG / TIFF / BMP
        ↓
Audiveris
        ↓
MXL / MusicXML
        ↓
MusicXML normalization
        ↓
SQLite canonical score
        ↓
검증 → 편집 → Revision → 조판 → Export
```

## OMR backend

기본 OMR provider는 Audiveris입니다.

- 입력: PDF 및 일반적인 스캔 이미지
- 실행: 외부 CLI
- 출력: MusicXML/MXL
- AudioScoreTool은 MXL인 경우 내부 MusicXML document를 추출해 `score.musicxml`로 정규화합니다.

기본 CLI contract:

```bash
audiveris -batch -transcribe -export -output <output-dir> -- <score-file>
```

Audiveris가 설치되어 있지 않으면 음원 채보/기존 MusicXML 편집은 계속 사용할 수 있고 PDF/이미지 가져오기만 비활성화됩니다.

## 원본 보존

OMR 결과만 저장하면 나중에 인식 오류를 원본과 대조할 수 없습니다. 따라서 원본 PDF/이미지는 곡 ID와 같은 managed asset 디렉터리에 보존합니다.

```text
assets/<song-id>/original-score.pdf
assets/<song-id>/original-score.png
...
```

Job 임시 디렉터리가 정리되어도 원본 악보는 Song 삭제 전까지 유지됩니다.

## 검증 정책

OMR 결과를 정답으로 간주하지 않습니다.

현재 즉시 적용되는 검증:

1. MusicXML parse/score root 검증
2. 마디 duration / 박자표 정합성
3. 일반 악기 음역 이탈
4. rest + lyric 등 표기 이상
5. tie 중복 / 빈 part 등 구조 이상
6. 선택적 LLM critic

향후 멀티모달 검증:

```text
Original page image
        +
Recognized MusicXML
        ↓ render
Recognized score image
        ↓
Vision comparison
        ↓
measure/staff discrepancy candidates
        ↓
사용자 검토
```

특히 accidental, beam, rest/note, tie/slur, voice 분리, 가사 anchor, 반복기호처럼 OMR에서 자주 틀리는 항목을 measure-level review 대상으로 표시하는 것이 목표입니다.

LLM/VLM이 직접 MusicXML을 자동 수정하는 방식은 기본값으로 사용하지 않습니다. 먼저 discrepancy candidate를 생성하고 사용자가 확인하거나 높은 confidence의 제한된 수정만 별도 승인 흐름으로 처리하는 것이 안전합니다.

## 파트/Staff 해석

OMR 결과의 part/staff 구조는 MusicXML part-list와 staff/clef/voice 정보를 기준으로 유지합니다. 추후 semantic classification을 추가할 경우 다음 정보는 보조 증거로만 사용합니다.

- part/staff label OCR
- clef
- pitch range
- monophonic/polyphonic density
- lyric 존재 여부
- percussion notation
- grand staff 관계

예를 들어 `lyrics + monophonic treble staff`는 vocal candidate가 될 수 있지만, 자동으로 Vocal이라고 확정하지는 않습니다.

## 라이선스 경계

Audiveris는 GNU AGPL v3로 배포됩니다. AudioScoreTool은 현재 Audiveris를 Python package로 링크하지 않고 별도 설치된 외부 실행 프로그램으로 호출합니다.

상용 installer에 Audiveris 자체를 번들하거나 수정 버전을 배포하는 경우에는 해당 배포 방식에 대한 AGPL 의무를 별도로 검토해야 합니다.
