# 음원 식별 파이프라인

AudioScoreTool은 파일명이나 모델 추론만으로 곡 정보를 결정하지 않습니다. 새 곡이 라이브러리에 들어오면 다음 순서로 clean data를 우선 사용합니다.

```text
Embedded audio tags
    ↓
ISRC
    ↓
AcoustID / Chromaprint fingerprint
    ↓
MusicBrainz title/artist fuzzy search
    ↓
모델/사용자 입력 fallback
```

## 1. Embedded tags

`mutagen`으로 MP3/FLAC/M4A 등에서 가능한 범위의 다음 정보를 로컬에서 읽습니다.

- title
- artist / album artist
- album
- date/year
- ISRC
- duration

`title + artist`가 모두 존재하면 네트워크 조회보다 이 정보를 우선합니다. 원본 파일은 managed asset으로 보존되고 식별 결과는 `source_identification` analysis에 provenance와 함께 저장됩니다.

## 2. ISRC

ISRC가 존재하면 일반 제목 검색보다 먼저 MusicBrainz recording lookup에 사용합니다. 정확한 identifier 경로이므로 fuzzy title matching보다 높은 우선순위를 갖습니다.

상용 모드에서는 MusicBrainz Web Service의 상용 이용 자격/계약이 확인되지 않은 상태에서 자동 네트워크 조회를 하지 않습니다.

## 3. AcoustID fingerprint

태그가 부족한 경우 선택적으로 Chromaprint의 `fpcalc`로 fingerprint를 생성하고 AcoustID Web Service에 조회합니다.

필요 조건:

- `fpcalc` 설치
- 등록된 AcoustID application client key
- `ACOUSTID_CLIENT_KEY` 환경변수

앱에 client key를 하드코딩하지 않습니다. 상용 모드에서는 별도 AcoustID 상용 이용 권한이 확인되지 않으면 lookup을 건너뜁니다.

AcoustID confidence가 0.90 이상일 때 후보로 선택하고, 자동 metadata 적용은 전체 정책상 0.92 이상에서만 수행합니다.

## 4. 자동 적용

고신뢰도 식별 결과는 다음에 동기화됩니다.

- Song DB title / artist
- MusicXML score title
- publication layout의 첫 페이지 제목

자동 적용 전에는 Revision snapshot을 생성하므로 이후 Undo가 가능합니다.

낮은 신뢰도의 결과는 분석 데이터로만 보존하고 기존 사용자 수정값을 덮어쓰지 않습니다.

## 5. 실행 시점

Desktop의 `SourceIdentificationController`는 곡 라이브러리를 주기적으로 확인하고 새 song을 발견하면 한 번 식별합니다. 따라서 사용자가 별도로 `곡 정보` 창을 열지 않아도 ingestion 이후 자동 enrichment가 시작됩니다.

OMR처럼 원본 오디오 asset이 없는 곡은 조용히 skip됩니다. 식별 실패는 채보/편집/내보내기 실패로 전파되지 않습니다.

## Setup Center

`Chromaprint / fpcalc`는 optional component입니다.

- macOS + Homebrew: 앱에서 `brew install chromaprint` 자동 설치 가능
- Windows/Linux: 공식 Chromaprint 배포판 또는 OS package manager 사용

태그가 충분하면 Chromaprint 자체가 필요하지 않습니다.

## 라이선스/서비스 경계

- Chromaprint client library: LGPL 2.1
- AcoustID fingerprint database/metadata: CC BY-SA 3.0
- AcoustID Web Service: 비상업 앱은 등록 후 무료 사용 가능, 상용 앱은 AcoustID OÜ와 별도 상용 사용 조건 확인 필요
- MusicBrainz core metadata와 공개 Web Service 사용 조건은 별도로 구분해서 처리

AudioScoreTool은 외부 서비스 이용 자격을 자동으로 가정하지 않습니다.
