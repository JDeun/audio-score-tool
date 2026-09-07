# 외부 데이터 보강 설계

AudioScoreTool은 모델이 이미 존재하는 깨끗한 정보를 다시 추측하지 않도록 **외부 데이터 → 신뢰도 검증 → 모델 fallback** 순서를 사용합니다.

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

92점 미만 후보는 사용자에게 보여주기만 하고 제목/아티스트를 자동 변경하지 않습니다.

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
POST /api/songs/{song_id}/enrich
```

기본 요청은 MusicBrainz metadata만 조회합니다. `lyrics_url_template`을 명시했을 때만 외부 lyrics provider를 호출합니다.

주요 옵션:

- `apply_high_confidence_metadata`
- `metadata_threshold`
- `musicbrainz_commercial_entitlement`
- `lyrics_provider_name`
- `lyrics_url_template`
- `lyrics_api_key_env`
- `apply_reference_lyrics`

## 향후 확장

- ISRC 우선 매칭
- 로컬 파일 ID3/MP4/Vorbis tag 우선 읽기
- AcoustID fingerprint 기반 recording identification
- YouTube title/uploader를 search hint로 분리
- lyrics provider별 정식 adapter와 라이선스 상태 UI
- composer/lyricist/work relationship를 출판 credit에 제안
- reference lyrics alignment confidence가 낮은 span만 사용자 검토 대상으로 표시
