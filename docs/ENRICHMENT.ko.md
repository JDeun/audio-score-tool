# 외부 데이터 보강 설계

AudioScoreTool은 모델이 이미 존재하는 깨끗한 정보를 다시 추측하지 않도록 **로컬 태그/식별자 → 외부 데이터 → 신뢰도 검증 → 모델 fallback** 순서를 사용합니다.

## 자동 음원 식별

새 곡이 라이브러리에 들어오면 Desktop의 `SourceIdentificationController`가 자동으로 식별을 시도합니다.

```text
Embedded tags
    ↓
ISRC
    ↓
AcoustID / Chromaprint fingerprint
    ↓
MusicBrainz fuzzy search
    ↓
모델/사용자 입력 fallback
```

- MP3/FLAC/M4A 등의 title/artist/album/date/ISRC/duration은 `mutagen`으로 로컬에서 먼저 읽습니다.
- title + artist가 충분하면 네트워크 조회 없이 그대로 우선 사용합니다.
- ISRC가 있으면 일반 제목 검색보다 먼저 MusicBrainz identifier lookup을 사용합니다.
- 태그가 부족하면 `fpcalc` + 등록된 `ACOUSTID_CLIENT_KEY`가 있을 때 AcoustID fingerprint lookup을 시도합니다.
- 자동 metadata 반영 threshold는 0.92입니다.
- 적용된 제목은 Song DB, MusicXML title, publication layout까지 동기화합니다.
- 식별 실패/네트워크 실패는 채보 실패로 전파되지 않습니다.
- OMR처럼 원본 audio asset이 없는 곡은 자동으로 skip됩니다.

세부 구현과 서비스/라이선스 경계는 `docs/SOURCE_IDENTIFICATION.ko.md`를 참고합니다.

## 메타데이터

기본 provider는 MusicBrainz입니다.

가져오는 후보 정보:

- 곡명 / recording title
- 아티스트
- 앨범/release
- 최초 발매일
- MusicBrainz recording/release ID
- ISRC
- 길이
- MusicBrainz search score

MusicBrainz core metadata는 CC0 범위가 넓지만, 공개 Web Service의 상용 사용 조건은 별도로 확인해야 합니다. 앱은 provider와 MBID, match score를 `external_enrichment` analysis에 함께 저장해 provenance를 유지합니다.

MusicBrainz 공개 API 정책에 맞춰:

- 명시적인 AudioScoreTool User-Agent 사용
- 앱 프로세스 기준 평균 1 req/s 이하 직렬화
- 자동 적용 threshold 기본 92%

를 적용합니다.

92점 미만 fuzzy 후보는 사용자에게 보여주기만 하고 제목/아티스트를 자동 변경하지 않습니다.

상용 모드에서는 공개 MusicBrainz Web Service를 무조건 호출하지 않습니다. 사용자가 상용 이용 자격/계약을 확인했다는 명시적 플래그가 있어야 호출합니다. 장기적으로는 상용 계약 endpoint나 로컬 CC0 dataset index를 별도 provider로 둘 수 있습니다.

## 가사

가사는 저작권 보호 대상일 수 있으므로 일반 검색 결과나 임의 웹페이지를 scraping하지 않습니다.

우선순위:

```text
허용된/계약된 lyrics API가 설정됨
    ↓ yes
Provider 가사 확보 + provenance 저장
    ↓
WhisperX word timing과 reference text 정렬
    ↓
사용자가 적용을 선택하면 MusicXML lyric 교정

    ↓ provider 없음 / 실패
WhisperX 전사 + 기존 시간 정렬
```

외부 가사 API는 현재 다음 형태의 HTTPS JSON provider adapter를 지원합니다.

```text
https://api.example.com/lyrics?artist={artist}&title={title}
```

응답은 `syncedLyrics`, `plainLyrics`, `lyrics` 중 하나를 포함할 수 있습니다. API key는 값 자체를 앱 설정에 저장하지 않고 환경변수를 통해 전달하는 방식을 사용합니다.

원격 endpoint는 HTTPS만 허용하며 localhost만 HTTP 예외를 허용합니다.

## Reference lyrics + acoustic timing

외부 provider의 텍스트를 그대로 시간축 정답으로 취급하지 않습니다.

```text
외부 provider
  → clean lyric text

WhisperX
  → word start/end timing

두 결과
  → SequenceMatcher 기반 token span alignment
  → 동일 token은 WhisperX timing 그대로 유지
  → 교체/삽입 token은 대응 ASR span에 보수적으로 분배
  → 한국어는 기존 Hangul syllable timing 확장
  → MusicXML vocal part에 재부착
```

따라서 역할은 명확히 분리됩니다.

- **문자열 정확도:** 외부 reference lyrics
- **시간/가창 근거:** 원음에서 얻은 WhisperX timing

가사를 악보에 적용할 때는 Revision snapshot을 먼저 만들므로 기존 Undo 흐름을 유지합니다. 정렬할 WhisperX timing이 없으면 외부 가사를 자동 적용하지 않습니다.

결과 provenance는 다음 analysis에 보존합니다.

- `source_identification`
- `external_enrichment`
- `external_lyrics`
- `reference_lyrics_alignment`

## 원칙

- 웹에서 발견했다는 이유만으로 가사를 저장하지 않음
- provider/라이선스 provenance를 잃지 않음
- 외부 데이터가 실패해도 채보가 실패하지 않음
- metadata는 high-confidence에서만 자동 반영
- clean lyrics가 있더라도 음표 타이밍은 원음/ASR alignment evidence를 활용
- 사람이 수정한 title/artist/lyrics를 외부 결과로 무조건 덮어쓰지 않음
- 상용 모드에서 공개 API의 상용 권한을 추정하지 않음

## API

```text
POST /api/songs/{song_id}/identify-source
POST /api/songs/{song_id}/enrich
```

`identify-source`는 managed original audio를 대상으로 로컬 태그/ISRC/AcoustID 순서의 자동 식별을 수행하고 결과를 cache합니다. `enrich`는 MusicBrainz fuzzy metadata와 선택적 lyrics provider를 사용합니다.

## 향후 확장

- YouTube title/uploader를 search hint와 authoritative metadata로 구분
- lyrics provider별 정식 adapter와 라이선스 상태 UI
- composer/lyricist/work relationship를 출판 credit에 제안
- reference lyrics alignment confidence가 낮은 span만 사용자 검토 대상으로 표시
- AcoustID/MusicBrainz identifier 결과가 충돌할 때 다중 evidence resolver 추가
