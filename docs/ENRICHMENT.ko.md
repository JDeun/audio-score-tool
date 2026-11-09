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

## Job 완료 자동 API 조회 + WhisperX 최종 가사 정렬 (#187)

오디오·YouTube 신규 채보에는 `auto_enrich=true`가 기본값입니다. 기존 저장된 Job은 SQLite migration에서 **false**로 유지해 예고 없는 네트워크 호출을 하지 않습니다. 사용자는 ‘새 악보 만들기’의 **곡 정보·가사 자동 보강** 스위치로 직접 끌 수 있습니다. 자동 호출에는 음원/Stem/악보 파일을 전송하지 않고, 명시적인 `아티스트 - 곡 제목` 형태의 제목에서 추출한 이름만 사용합니다. YouTube uploader/채널명은 저작자나 가수라고 단정하지 않습니다.

자동 흐름: 파일명 또는 영상 제목에서 `Artist - Track` 패턴을 확인 → 개인 모드에서 LRCLIB 정확 일치 **API 먼저** 조회(WhisperX 요청 전) → 가사 API 텍스트가 있으면 WhisperX가 계산한 실제 단어별 타이밍과 정렬해 MusicXML 음표에 붙임 → API 없음/429/정렬 신뢰도 부족 시 WhisperX STT 텍스트와 타이밍 그대로 유지. 외부 API 실패는 기본 채보 Job 성공을 취소하지 않습니다. 사용자가 가사 인식을 껐거나 WhisperX가 설치되지 않았다면 앱에서 가사 없는 악보를 정상적으로 만들되 API 타이밍을 임의로 만들지 않습니다.

Job이 `done` 상태가 되면 모델 추론 자원을 해제한 뒤 완성 Song을 안전하게 생성하고, 같은 제목 힌트로 MusicBrainz recording/work의 고신뢰도 메타데이터를 조회하여 **Song revision과 출판 크레딧을 atomic/undoable 변경**으로 반영합니다. 저작자 Work 관계가 확인되지 않으면 임의로 저자 필드를 채우지 않습니다. Song의 외부 자동 조회 기록은 `automatic_enrichment` 분석 타입으로 남습니다. 작업 완료가 API 네트워크 연결 성공을 의미하지 않으며, 실패한 경우 사용자 ‘곡 정보’ 화면에서 수동으로 다시 조회·수정할 수 있습니다.

주의: 표준 음원 파일명이나 YouTube 제목에 아티스트-곡명 구조가 없다면 자동 식별은 보수적으로 건너뜁니다. 예: `American Idiot` 단독 제목은 출처 모호성 때문에 자동으로 특정 밴드·작곡가를 할당하지 않습니다. 배포용 실수정 악보 품질, 가사 저작물 재배포, 상업용 외부 API 자격과 모델 바이너리 배포 정책은 별도 검증합니다.

## 자동 식별 입력 우선순위 및 Unknown 상태 (#187)

개인용 새 음원에서 자동 보강을 켠 경우 소스 종류별 검색 근거를 명확히 구분합니다.

- **로컬 음원**: 원본 파일의 `mutagen` embedded metadata 중 title/artist를 우선 사용합니다. 태그 둘이 유효하면 파일명은 사용하지 않습니다. 태그가 없으면 원래 업로드한 `아티스트 - 제목` 파일명에서 조회 키워드를 추출합니다. 한쪽 태그만 있고 파일명에도 짝이 있으면 서로 일치하는 경우에만 합칩니다. 서로 충돌하면 외부 조회를 포기합니다. 앨범 태그는 가사 API에 보조 검색 단서로만 전달합니다.
- **YouTube**: URL에서 식별된 **영상 제목만** `아티스트 - 곡명` 형식의 조회 단서로 사용합니다. YouTube uploader/채널명, 오디오 다운로드 파일명이나 재생 파일 태그를 가수/작곡가/작사가로 간주하지 않습니다.
- **MusicBrainz 신뢰성**: 자동 경로에서는 기존 recording 점수 ≥92와 별도로 입력 제목·아티스트의 casefold/Unicode 정규화 **정확 일치**를 요구합니다. 잘못된 상위 검색 후보가 나와도 Song을 그 곡으로 변경하지 않습니다. 편집기에서 수동 검색할 때의 기존 검색 기준과 구분됩니다.
- **검색 단서 없음 / 검증된 결과 없음**: 원본 파일명·영상 제목을 검증된 제목으로 남겨두지 않고 새 Song의 title, artist, album, performer, release_date, composer, lyricist를 명시적인 `Unknown`으로 설정합니다. 이 상태는 MusicXML/첫 페이지 크레딧과 Song SQLite revision에 저장되며 Undo로 원상복구할 수 있습니다. 이전에 사용자가 편집한 Song(revision 변경 등)을 뒤늦은 조회가 덮어쓰지 않습니다. API 응답 장애도 같은 미확인 표시로 처리하되 `automatic_enrichment` 근거에 오류/미실행 상태를 기록합니다.
- **이후 수정**: 사용자가 곡을 직접 식별하거나 외부 API에서 진짜 고신뢰도 데이터를 찾으면 앱이 자동 기입한 `Unknown` 필드만 해당 정보로 교체할 수 있습니다. 수동으로 작성한 크레딧은 유지합니다.
- **가사**: 신뢰할 만한 title/artist가 있으면 LRCLIB API를 우선 시도하며, 없거나 실패하면 LRCLIB 검색은 건너뛰고 원음/보컬 Stem에 대한 **기존 WhisperX STT** 경로를 실행합니다. 단, 사용자가 가사 인식을 끄거나 WhisperX가 설치되지 않은 환경은 사용자가 정한 동작을 존중하며 가사를 생성한 척하지 않습니다. 곡 정보를 모른다는 이유로 음원 악보 채보 자체를 취소하지 않습니다.

## Unknown 메타데이터 후수정 및 API 재조회 (#187)

곡 라이브러리/악보 편집 화면에서 자동 식별 결과가 `Unknown`인 Song을 열면 **곡 정보 확인 필요** 안내가 나옵니다. ‘악보 정보 직접 수정’을 누르면 기존 **제목·정보** 인스펙터로 이동하고, ‘메타데이터 관리·재조회’를 누르면 원래 제공되던 **곡 정보 보강** 팝업을 엽니다. 팝업은 선택된 Song의 canonical title/artist와 현재 publication 설정(앨범, 가수·연주자, 발매 정보, 작곡가, 작사가)을 함께 읽습니다.

사용자는 팝업에서 각 필드를 직접 고쳐 **메타데이터 저장**을 누를 수 있습니다. 저장은 기존 `PATCH /api/songs/{song_id}/credits`의 optimistic `expected_revision` 검증 및 단일 Undo 스냅샷을 재사용하므로 Song, MusicXML, 출판 크레딧이 따로 저장되지 않습니다. 다른 창/인스펙터에서 먼저 악보를 수정한 경우 409 충돌을 안내하고 수동 편집을 덮어쓰지 않습니다. 팝업에서 수정하지 않은 편곡자/권리 표기도 별도로 보존합니다.

**곡 정보·가사 자동 조회**는 재입력된 곡명과 아티스트를 사용합니다. 팝업에 저장되지 않은 필드가 있으면 동일 atomic API로 **먼저 저장한 후** 조회합니다. API 요청은 `require_exact_match=true`로 제목과 가수가 모두 일치하는 MusicBrainz 후보만 자동 반영합니다. 기존 MusicBrainz 신뢰도 임계값(≥92%)은 유지하고, 사용자가 입력한 앨범·작사·작곡 등은 검증된 API 후보가 나타나도 덮어쓰지 않습니다. 자동 생성됐던 `Unknown` 필드만 검증된 값으로 채울 수 있습니다.

`Unknown` 자체는 유효한 곡명/아티스트가 아니므로 해당 상태에서 재조회 버튼을 누르면 **먼저 실명 입력 필요** 메시지를 표시하고 네트워크 조회를 하지 않습니다. 편집 중 곡을 바꾸거나 늦게 도착한 API 응답이 다른 Song에 쓰이지 않도록 선택된 Song ID에 요청을 묶습니다. 조회가 실패하더라도 WhisperX/STT 가사와 이미 수정한 악보는 유지됩니다.

## 외부 실제 API 호환성 검증 및 조회 대체 경로 (#187)

`External Metadata and Lyrics API Live Contract` GitHub Actions는 실제 MusicBrainz와 LRCLIB 서비스에 **가사·음원·파일 없이 공개 곡명·아티스트만 질의**하여 API 응답이 제품의 파서와 맞는지 확인합니다. 고정된 서비스 예제와 메타데이터 조회만 수행하며, 응답의 **가사 텍스트/전체 HTTP 본문은 로그·아티팩트로 절대 업로드하지 않습니다**. 단, 서비스 제공자 측에는 요청한 검색어가 전송됩니다. 수집 결과는 `live-provider-contract.pending.json`에 연결/검증 상태와 HTTP 코드만 기록됩니다.

PR 변경 시 자동 실행되며, 수동 `workflow_dispatch`에서는 `strict_live=true`를 선택해 서비스 하나라도 확인되지 않으면 실패시키는 재현 검사를 할 수 있습니다. 일반 CI에서 공용 API의 429/5xx/네트워크 장애는 `inconclusive`로 구분하고, **CI가 성공했다고 외부 서비스 양쪽이 응답했다고 단정해서는 안 됩니다**. 반드시 로그 또는 metadata-only 보고서의 `both_provider_contracts_live`를 확인하세요.

실제 [2026-11-09 검증 실행](https://github.com/JDeun/audio-score-tool/actions/runs/42569653243)에서는 MusicBrainz 곡명·아티스트 일치와 LRCLIB 공식 테스트곡의 실제 가사 응답을 확인했습니다. 해당 Green Day 녹음 후보의 Work→songwriter 연결은 `ambiguous_or_missing_work`이므로, 이번 실측만으로 작곡·작사가 자동 입력을 보장할 수 없습니다. 그런 경우 앱은 임의 크레딧을 만들지 않고 `Unknown`을 유지합니다.

LRCLIB 클라이언트는 `/api/get`에서 지정된 버전/앨범의 데이터를 찾지 못했을 때 공식 `/api/search`를 **최대 한 번** 사용합니다. 두 단계 모두 title/artist가 정규화 후 정확 일치하고, 앨범이 명시됐다면 albumName도 정확 일치해야 합니다. `search`에서 여러 개의 동일 후보가 생기면 라이브/리믹스/다른 앨범 버전을 임의로 선택하지 않고 WhisperX STT를 사용합니다. 429나 다른 HTTP 장애에는 추가 검색을 하지 않고 기존 ASR fallback으로 전환합니다. 음악적 타이밍은 WhisperX를 통해서만 확인됩니다.
