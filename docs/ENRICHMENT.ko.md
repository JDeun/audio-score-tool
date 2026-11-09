# 외부 데이터 보강 설계

AudioScoreTool은 모델이 이미 존재하는 깨끗한 정보를 다시 추측하지 않도록 **로컬 태그/식별자 → 외부 데이터 → 신뢰도 검증 → 모델 fallback** 순서를 사용합니다.

## 자동 음원 식별

**외부 서비스 식별은 명시적 실행**입니다. 사용자가 곡 라이브러리 → 곡 정보 → 원본 음원 자동 식별을 클릭하면 `EnrichmentController`가 식별 API를 호출합니다. 새로운 오디오 Job 등록 시에는 설정에서 직접 켠 경우에 한해 **로컬 embedded title/artist 태그만 자동 분석**합니다. 이 로컬-only opt-in 경로는 AcoustID/MusicBrainz 네트워크 조회와 fingerprint를 실행하지 않으며, 한 번의 Undo Revision에만 기록합니다([#100](https://github.com/JDeun/audio-score-tool/issues/100)).

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

## 제목·앨범·작곡/작사·가사 외부 API 기본 경로 (#187)

곡 정보 창의 ‘곡 정보·가사 자동 조회’를 누르면 MusicBrainz에서 제목/가수/앨범/발매일을 조회합니다. 92% 이상의 신뢰도 있는 recording ID를 찾았을 때만 해당 recording의 **performance→work 관계**를 확인하고, work의 **composer/lyricist→artist 관계**가 실제 존재하는 이름만 악보 작사·작곡 크레딧으로 넣습니다. 가수와 작곡가가 동일하다고 추정하지 않습니다. work가 둘 이상이거나 작성자 관계가 없으면 필드를 공란으로 둡니다.

기존 수동 크레딧(앨범·가수·발매·작사·작곡)은 자동 결과로 덮어쓰지 않습니다. Song 제목/가수, MusicXML first-page credits와 SQLite publication JSON은 동일한 undoable revision/transaction으로 저장되고 이전 revision 복원 시 모두 원복됩니다. 임의의 출처 해석/수정 내역은 별도 사용자 선택이 필요합니다.

개인용 모드에서 외부 가사를 자동으로 찾아볼 때 우선 [LRCLIB](https://lrclib.net/docs)의 `/api/get` (track + artist, 가용할 경우 album)을 사용합니다. LRCLIB는 공개 API 키가 필요 없는 서비스지만, 반환한 track/artist를 **문자열로 정확히 대조**하고, instrumental·불일치·404를 성공으로 취급하지 않습니다. 사용자가 별도 허가 받은 가사 Provider URL을 등록했다면 그 설정을 우선합니다. 원본 오디오 바이트는 LRCLIB/MusicBrainz에 전송하지 않고 곡명·가수 등 검색 정보만 전달합니다.

API가 없거나 실패했을 경우 **이미 선택적으로 실행된 WhisperX 가사 인식 및 정렬을 그대로 사용**합니다. API에서 가져온 가사를 MusicXML 음표에 적용하려면 WhisperX가 제공한 단어 시간 정보가 있어야 합니다. 타이밍 증거가 없으면 API 텍스트는 출처와 함께 보존하지만 가사가 악보에 동기화됐다고 주장하지 않습니다. ‘가사 ASR 켜기’가 비활성화된 Job에는 새 음성 인식 결과가 없을 수 있습니다.

상업 모드에서 MusicBrainz 접근 자격이 없더라도 전체 `enrich` 작업을 거부하지 않고, 검증된 사용자 지정 가사 Provider 또는 기존 로컬 WhisperX를 사용할 수 있습니다. 개인용 LRCLIB 기본 접근은 상업 모드에서 자동 활성화되지 않습니다.
