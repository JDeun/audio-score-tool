# Public CPU vocadito 결과: 7개 후보

[Actions 실행 42819292731](https://github.com/JDeun/audio-score-tool/actions/runs/42819292731)에서 공개 vocadito v3 40개를 7개 후보 모두 CPU로 완료했다. 실행 checkout은 `fc423b0cef068ce6c90697b1a763971be95a3f55`, 당시 PR head는 `4fd1f52181ded75d130a5282118e2b51ec0bb380`이다. 두 SHA는 서로 다른 역할이다. [결과 메타데이터](CPU_PUBLIC_VOCADITO_RESULTS_2026-11-10.json)에 모델 revision, 가중치 SHA, 런타임, 실행 스크립트 SHA와 8개 artifact ID·ZIP digest를 기록했다. 기존 실패 실행 영수증은 유지하며 이번 완료 결과로 덮어쓰지 않았다.

원본 ZIP의 동일한 40개 녹음과 A1/A2 원래 Hz 주석을 사용했다. 검증된 영수증은 7×40 소스·주석·F0 해시, macro 재집계와 Actions summary 일치를 확인한다. 원시 예측은 공개 artifact에 없으므로 여기서 재채점하지 않았다. 학습 데이터 중복 여부는 미확인이다.

## 음표 전사

40개 녹음과 두 주석자의 macro F1이다. onset은 50ms·50 cents, onset+offset은 추가로 종료 시각 max(50ms, 기준 음가의 20%) 허용이다.

| 후보 | onset F1 | onset+offset F1 |
|---|---:|---:|
| YourMT3+ | 0.54340549 | 0.30937724 |
| Basic Pitch | 0.49102129 | 0.31583077 |
| MR-MT3 | 0.18263075 | 0.07705163 |

YourMT3+는 onset, Basic Pitch는 onset+offset에서 높았다. 지표가 엇갈리므로 자동으로 단일 승자를 선정하지 않는다.

## F0 추적

음표 전사와 별도 과제다. RPA는 raw pitch accuracy, OA는 overall accuracy, FA는 무성 구간 false alarm, 옥타브 오류는 기준 유성 프레임당 비율이다.

| 후보 | RPA | OA | FA | 옥타브 오류 |
|---|---:|---:|---:|---:|
| torchcrepe full | 0.88622704 | 0.83849756 | 0.26836578 | 0.00076820 |
| torchcrepe tiny | 0.87981949 | 0.83174799 | 0.27491606 | 0.00154907 |
| pYIN | 0.80528736 | 0.72524536 | 0.43519268 | 0.00132706 |
| YIN | 0.62843586 | 0.68691592 | 0.19229621 | 0.00291361 |

이 결과는 사람의 악보 수정량, PDF 읽기 품질 또는 상용 배포 적합성 평가가 아니다. 모델·품질 승인과 속도 순위 승인은 false다. PR workflow는 관련 경로를 변경한 PR의 개설·재개설에서 자동 실행하며, 후속 push 및 기반 브랜치 병합으로 7개 장시간 작업을 반복하지 않는다. `workflow_dispatch`로 명시적 재실행은 가능하며 일반 CI는 그대로다.
