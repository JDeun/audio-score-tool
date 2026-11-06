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

## 5. 실행 시점 — 현재 구현

현재 데스크톱에는 별도의 자동 실행 `SourceIdentificationController`가 없습니다. **외부 서비스가 포함될 수 있는 식별은 사용자가 곡 라이브러리에서 `곡 정보 → 원본 음원 자동 식별`을 클릭할 때만** `POST /api/songs/{song_id}/identify-source`를 호출합니다.

설정의 `새 음원 태그 자동 식별`은 **기본 OFF인 별도 옵트인 기능**입니다. 활성화하면 새 오디오 Job이 Song 라이브러리에 최초 등록되는 시점에만 앱 내부 `mutagen`으로 embedded title/artist를 읽습니다. 이름과 아티스트가 모두 있어 신뢰도 1.0이면 SQLite Song·MusicXML 제목·출판 조판을 원자적으로 한 Revision에 반영합니다. Undo로 되돌릴 수 있습니다. 등록 후 이미 편집된 곡은 덮어쓰지 않습니다.

이 등록 시점의 로컬 식별은 `ISRC` 조회, AcoustID fingerprint/`fpcalc`, MusicBrainz 또는 외부 HTTP 요청을 **절대 수행하지 않습니다**. 원본 오디오는 Job 임시파일과 별개인 Song managed asset `original-audio.*`에 보존하며, 설정을 꺼도 수동 식별이 원본을 찾을 수 있습니다. 옵션 해제는 향후 등록되는 Song에 적용됩니다.

이 버튼의 '자동'은 *사용자가 실행을 시작한 이후* 로컬 태그 → ISRC → 조건부 AcoustID/MusicBrainz 후보 선택 과정을 자동 처리한다는 뜻이며, 곡 등록 직후의 무인 백그라운드 네트워크 요청을 뜻하지 않습니다.

- `refresh=false`로 API를 호출하면 저장된 분석 결과를 재사용할 수 있고, 현재 Desktop의 명시적 버튼은 최신 조회를 위해 `refresh=true`를 보냅니다.
- 사용자 동의 없이 외부 식별 서비스를 자동 호출하지 않습니다. 상용 모드에서 MusicBrainz/AcoustID는 해당 서비스의 사용 자격 확인이 있어야 조회할 수 있습니다.
- 상용 모드라도 **로컬 embedded-tag 식별은 두 외부 서비스 권한을 체크하지 않고 사용할 수 있습니다.** 권한 체크는 MusicBrainz/AcoustID 각각의 네트워크 조회에만 적용됩니다([#102](https://github.com/JDeun/audio-score-tool/issues/102), [PR #103](https://github.com/JDeun/audio-score-tool/pull/103)).
- 오디오 원본이 없는 OMR/MusicXML/MIDI 가져오기 곡은 `no_audio` 결과로 끝나며, 외부 조회를 하지 않습니다.
- 식별 및 외부 조회 실패는 채보·편집·내보내기 실패로 전파되지 않습니다.

로컬-only 자동 태그 식별은 사용자의 설정을 통한 opt-in으로 구현했습니다([#100](https://github.com/JDeun/audio-score-tool/issues/100)). **외부 AcoustID/MusicBrainz의 무인 백그라운드 식별은 미구현이며 동의/상용 서비스 권한 없이 자동 실행하지 않습니다.**

## Setup Center

`Chromaprint / fpcalc`는 선택적 acoustic fingerprint 구성요소입니다. **패키지 앱은 Homebrew/winget 등 시스템 패키지 매니저로 설치하지 않습니다.** 앱 관리형 공급이 승인·구현되기 전에는 해당 기능이 준비되지 않았음을 표시해야 합니다. 소스 개발 환경의 별도 실행 파일 설정은 일반 사용자 설치 경로가 아닙니다.

태그가 충분하면 Chromaprint 자체가 필요하지 않습니다.

## 라이선스/서비스 경계

- Chromaprint client library: LGPL 2.1
- AcoustID fingerprint database/metadata: CC BY-SA 3.0
- AcoustID Web Service: 비상업 앱은 등록 후 무료 사용 가능, 상용 앱은 AcoustID OÜ와 별도 상용 사용 조건 확인 필요
- MusicBrainz core metadata와 공개 Web Service 사용 조건은 별도로 구분해서 처리

AudioScoreTool은 외부 서비스 이용 자격을 자동으로 가정하지 않습니다.
