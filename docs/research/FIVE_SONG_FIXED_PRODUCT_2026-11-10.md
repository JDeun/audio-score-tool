# 고정 보컬 리드 제품 경로: 5곡 검증

5곡 모두 WAV 업로드 → Job → Song → PDF/MusicXML/MIDI export를 완료했다. 실행 commit은 `918e6dec1cd25140304f763d835b528fa8d73a2c`이고 원본 보고서의 SHA256, 모델 revision·weight SHA, 곡별 입출력 SHA와 개수는 [메타데이터](FIVE_SONG_FIXED_PRODUCT_2026-11-10.json)에 기록했다. YouTube 새 다운로드는 없었고 lyrics와 auto_enrich는 껐다. SoundFont 재합성은 실행하지 않았다. 전문가 정답은 없으며 quality와 최종 모델 승인 모두 false다.

| 곡 | 선택 원본 음표 | 해석된 음표 | 격자 누락 | PDF 페이지 |
|---|---:|---:|---:|---:|
| Me So Bad | 564 | 545 | 19 | 5 |
| FANCY | 710 | 695 | 15 | 7 |
| American Idiot | 311 | 308 | 3 | 9 |
| 나의 노래 | 605 | 551 | 54 | 5 |
| 사건의 지평선 | 623 | 594 | 29 | 7 |

최종 export는 해석된 음표의 pitch와 onset/offset을 2ms 이내로 보존했다. 이는 **해석 결과의 변환 보존 검사**이며 원곡 정답 정확도가 아니다. 독립 YIN은 안정적인 일부 음표만 비교해 옥타브·음높이 의심을 경고하며 전체 정확도나 전문가 판정이 아니다. 각 PDF에서 한 페이지만 시각 검토해 음표, 코드, 키, 박자, 제목 표시를 확인했다. 아래쪽 큰 여백, 복잡한 타이·쉼표와 낮은 음의 덧줄이 보였다. 전 페이지나 원곡 정답을 검증한 것은 아니다.

별도 복사본에서 `2bed2f94a9e210e315a9c47a743a85d49184e89a`로 실제 DELETE API 5회 후 SongStore를 다시 열었다. 원음 SHA, raw evidence 248개 파일 SHA, canonical XML과 revision이 보존됐다. 원본 앱 경로는 복사본으로 매핑했다. 일괄 cleanup API는 이 실데이터 검사에서 별도로 실행하지 않았으며, 관련 회귀 테스트와 구분한다.
