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

## 가사

가사는 저작권 보호 대상일 수 있으므로 일반 검색 결과나 임의 웹페이지를 scraping하지 않습니다.

우선순위:

```text
허용된/계약된 lyrics API가 설정됨
    ↓ yes
Provider 가사 확보 + provenance 저장

    ↓ no / 실패
WhisperX 전사 + 기존 시간 정렬
```

외부 가사 API는 현재 다음 형태의 HTTPS JSON provider adapter를 지원합니다.

```text
https://api.example.com/lyrics?artist={artist}&title={title}
```

응답은 `syncedLyrics`, `plainLyrics`, `lyrics` 중 하나를 포함할 수 있습니다. API key는 값 자체를 앱 설정에 저장하지 않고 환경변수를 통해 전달하는 방식을 사용합니다.

원격 endpoint는 HTTPS만 허용하며 localhost만 HTTP 예외를 허용합니다.

## 원칙

- 웹에서 발견했다는 이유만으로 가사를 저장하지 않음
- provider/라이선스 provenance를 잃지 않음
- 외부 데이터가 실패해도 채보가 실패하지 않음
- metadata는 high-confidence에서만 자동 반영
- clean lyrics가 있더라도 음표 타이밍은 원음/ASR alignment evidence를 활용
- 사람이 수정한 title/artist/lyrics를 외부 결과로 무조건 덮어쓰지 않음

## API

```text
POST /api/songs/{song_id}/enrich
```

기본 요청은 MusicBrainz metadata만 조회합니다. `lyrics_url_template`을 명시했을 때만 외부 lyrics provider를 호출합니다.

## 향후 확장

- ISRC 우선 매칭
- 로컬 파일 ID3/MP4/Vorbis tag 우선 읽기
- AcoustID fingerprint 기반 recording identification
- YouTube title/uploader를 search hint로 분리
- lyrics provider별 정식 adapter와 라이선스 상태 UI
- reference lyrics ↔ WhisperX word timing forced alignment
- composer/lyricist/work relationship를 출판 credit에 제안
