# AudioScoreTool — Repository Context

이 파일은 사람과 코드 분석 도구가 프로젝트의 현재 범위를 빠르게 오해 없이 파악할 수 있도록 핵심 계약만 요약합니다.

## 이 프로젝트는 무엇인가

AudioScoreTool은 **단음 pitch detector나 보컬 채점 모듈이 아닙니다.** 완성된 혼합 음원, YouTube 오디오, 기존 PDF/이미지 악보를 출발점으로 **편집·검증·출판 가능한 MusicXML 악보를 만드는 local-first desktop workspace**입니다.

핵심 흐름은 다음과 같습니다.

```text
mixed audio / YouTube
  -> polyphonic multi-instrument AMT
  -> MIDI / MusicXML
  -> chord + lyric alignment
  -> deterministic / acoustic / optional vision·LLM validation
  -> DB-backed editing + revisions
  -> publication layout
  -> explicit MusicXML / MIDI / PDF / part export

PDF / image score
  -> Audiveris OMR
  -> same canonical MusicXML workflow
```

## 채보 엔진 계약

현재 product-facing transcription engine은 다음 계열입니다.

- MuScriptor: 개인/비상업 품질 우선
- MT3-Infer + YourMT3+: 상용 모드 품질 우선 후보
- MT3-Infer + MR-MT3: permissive provenance fallback
- AudioScore Native: project-owned checkpoint를 위한 실험/확장 경로

이 엔진들은 API에서 다음 capability를 명시합니다.

- `task_family = automatic_music_transcription`
- `input_mode = mixed_audio`
- `supports_polyphonic = true`
- `supports_multi_instrument = true`
- `supports_real_time = false`

CREPE/SPICE 같은 monophonic pitch tracker는 현재 제품의 핵심 transcription backend가 아닙니다. 보조 pitch evidence가 필요해질 수는 있지만, 이를 main AMT engine으로 교체하면 보컬·피아노/기타·베이스·드럼 등을 포함하는 현재 제품 목표를 축소하게 됩니다.

## 품질 평가 계약

단순 pitch/onset F1 하나만으로 상용 품질을 판정하지 않습니다. benchmark는 최소한 다음을 분리해서 봅니다.

- note onset precision / recall / F1
- onset MAE
- note offset MAE
- instrument-aware precision / recall / F1
- lyrics alignment coverage
- chord/lyrics/OMR 품질
- 실제 사람이 수정한 note/chord 수
- 최종 악보까지 걸린 편집 시간
- runtime / peak resource usage

가장 중요한 제품 KPI는 **최종 사람이 수정하는 시간**입니다.

## 실시간 처리

현재 제품은 offline/near-offline 악보 제작 도구입니다. 실시간 streaming transcription은 목표 기능이 아닙니다. 따라서 mobile/web SDK 또는 low-latency streaming 대응 여부를 현재 제품 완성도의 필수 기준으로 평가하지 않습니다.

## 상업성 경계

AudioScoreTool 자체 코드는 Apache-2.0이지만 실제 유료 배포 가능성은 선택한 모델 checkpoint와 외부 도구의 라이선스/배포 방식에 따라 달라집니다. `usage_mode=commercial`은 알려진 비상업 모델(MuScriptor public weights)을 차단하며, YourMT3+ 계열은 고정 revision 기준 provenance 검토가 필요합니다.

## 현재 제품 포지셔닝

가장 가까운 범주는 다음입니다.

> **AI-assisted sheet music production workspace**

교육용 음정 채점기, 단음 멜로디 추출기, 실시간 튜너가 아닙니다.
