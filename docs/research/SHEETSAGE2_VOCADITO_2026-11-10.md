# 공식 SheetSage2 실추론 및 제품 연결

공식 `m-a-p/SheetSage2`를 실제로 내려받아, 원본 vocadito v3 40개를 전부 CPU 추론했다. 다운로드·실행·악보 변환 성공과 음악적 품질 승인을 구분한다. **이번 결과로 최소 수정 출판용 최종 모델을 승인하지 않는다.**

## 고정 출처와 실행

- [공식 모델](https://huggingface.co/m-a-p/SheetSage2/tree/b83c3d79a6d98bcffaf8f9ed112c90aa887887bc): revision `b83c3d79a6d98bcffaf8f9ed112c90aa887887bc`, weights SHA-256 `b235f68091a5f5b644000f2b5acb57d1e70432aca2b34ab1b9cf27236e1f4274`.
- [MERT 부모](https://huggingface.co/m-a-p/MERT-v2-FullSong/tree/d8ba1c745e733b3908ce6ad16ebeb17ac7600a42): 모델 config가 지정한 revision `d8ba1c745e733b3908ce6ad16ebeb17ac7600a42`, weights SHA-256 `e6dd2ab187d6dd62b6521cd7d8f932e237acf0c5757745a7232082e28391350d`. 최신 main으로 바꾸지 않았다.
- source/config/license/weights의 전체 SHA는 [pins](../../benchmarks/tier2/sheetsage2-pins.json)에 있다. 원격 Python을 검토하고 고정 파일을 재검증한 뒤 `local_files_only=True`, offline 환경에서 실행했다. 두 weights는 합계 2,758,551,412 bytes이며 공개 저장소에 포함하지 않는다.
- 두 모델은 CC BY-NC 4.0이며 이번 공개 snapshot은 ungated다. 개인/비상업 연구에만 연결하고 상용 실행을 차단한다. 라이선스 수락이나 인증이 필요하다는 이유로 이번 테스트를 미루지 않았다.
- 별도 Python 3.11.15, torch/torchaudio 2.8.0, transformers 4.45.2, numpy 1.24.3, mir_eval 0.8.2. 앱 Python 3.12/music21 환경과 프로세스로 분리한다. 공식 CPU float32, seed 0, threads 4, `preset=default`, 기본 300초 window, 전체 task prompts다. WAV를 channels-first waveform과 실제 sample rate로 전달해 공식 24kHz resampler를 사용했다.
- 실행 소스 `bebae1158aa10cb783b8a116d4c2e9441648d64a`와 당시 파일 SHA를 [전체 metadata 결과](SHEETSAGE2_VOCADITO_2026-11-10.json)에 보존한다. 이후 제품 어댑터 변경을 당시 실행으로 소급하지 않는다.

```bash
PYTHONPATH=src HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m scripts.run_sheetsage2_vocadito \
  --archive /private/vocadito.zip --snapshot /private/sheetsage2 \
  --output /private/new-sheetsage2-vocadito
```

## 같은 보컬 음원·정답에서 얻은 결과

[기존 MR-MT3/YourMT3+ 실행](VOCADITO_VOCAL_BASELINES_2026-11-09.md)과 똑같은 원본 ZIP, 40 WAV, 독립 주석자 A1/A2 CSV SHA를 사용했다. 시작 50ms, 실제 Hz 음높이 50cents, 종료 max(50ms, 정답 음가의 20%)다. 반올림·정답 기반 이동·옥타브 수정을 하지 않았고 빈 예측도 0점으로 포함했다. 40개×2명 F1의 단순 평균이다.

| 모델 | 엄격 onset F1 | 엄격 onset+offset F1 | 실행 / 빈 보컬 |
| --- | ---: | ---: | --- |
| MR-MT3 | 18.26% | 7.71% | 40/40 / 0 |
| YourMT3+ | 54.31% | 30.86% | 40/40 / 0 |
| 공식 SheetSage2 | 0.00% | 0.00% | 40/40 / 1 |

SheetSage2의 **보조 pitch-class onset F1은 39.84%**다. 원래 Hz의 소수 semitone 오차를 유지한 채 옥타브만 접은 보조 계산이며 엄격 F1을 대체하지 않는다. 모델 카드의 melody F1 역시 pitch-class/onset이며 다른 데이터셋 점수다. 여러 샘플에서 보컬 예측과 정답 간 옥타브 차이를 확인했다. 전체 40개가 엄격 기준 0인 결과를 숨기거나 정답으로 옥타브를 보정해 재승인하지 않는다. 이것은 이 데이터와 이 실행 설정에서의 결과이며 모든 음악에 대한 모델 성능 판정은 아니다.

CPU 추론·평가 합계 1,472.52초다. 다른 개발 검사도 실행 중이었고 이전 AMT는 threads 2였으므로 전용 하드웨어 속도 비교가 아니다. 16GB M4에서 별도 MPS 시도는 메모리 압박과 지연으로 중단했고 성공 또는 품질 점수로 포함하지 않았다. 정확한 peak RSS/VRAM 계측과 Windows 실추론은 미완료다. 사전학습 중복도 미확인이다.

## 제품 연결과 결정

공식 LAB의 코드 전위·beat/downbeat·변박·key와 원본 ABC/MIDI/playback을 보존한다. ABC의 명시적 Vocal 성부만 가져오고, music21이 누락하는 `Z` 여러 마디 쉼표를 선언 박자/음가로 확장한다. 원본 마디 수·음가·offset과 playback map이 다르면 실패한다. 이 변환은 39/40에서 성공하고, 보컬이 비어 있는 1곡은 명확히 실패한다.

canonical MusicXML은 모델의 악보용 리듬과 조표·코드를 유지한다. 원본 성능 MIDI와 별도로 마디별 audio clock을 적용하고, pickup/끝마디의 인위적 padding은 별도 숨김 tempo로 처리한다. padding은 quarter당 1µs로 직렬화하며, padding 없는 첫 마디의 beat-domain 시작 offset은 보고서에 남긴다. 이는 마디 안 연주 시간을 원본 그대로 보존하는 무손실 변환이 아니다. 원본 예측을 덮어쓰지 않는다.

`AST_SHEETSAGE2_CMD`와 `AST_SHEETSAGE2_SNAPSHOT`이 준비된 개발 환경에서만 Lead Sheet 엔진으로 선택할 수 있다. 업로드/YouTube 접수·SQLite 작업 선택·실행·재시도·UI까지 연결한다. Demucs 없이 직접 실행하고 다른 악보 모드는 접수 전에 거절한다. 코드 재추론과 MIDI pickup heuristic으로 모델의 악보를 다시 쓰지 않는다. 기존 Song/revision/명시적 export 경로를 재사용한다. packaged 앱에는 검증·게시된 managed runtime이 없어 선택을 허용하지 않는다.

결정: **optional noncommercial research engine으로 유지, 최종/상용 기본 모델 승격은 거절**. 보컬 음높이 정확도는 이 데이터에서 YourMT3+가 더 높지만, 그것만으로 반주 코드·박자·키·출판 수정량의 승자를 결정할 수 없다. #34/#43/#172/#200의 전체 수용 조건은 충족되지 않았다. 지정한 다섯 곡은 개발 40개와 분리해, 고정된 SheetSage2 설정으로 제품 실행 검사를 진행한다. 정답·사람 수정량·합격선이 없는 상태의 출력 성공을 최종 인수 합격으로 기록하지 않는다.
