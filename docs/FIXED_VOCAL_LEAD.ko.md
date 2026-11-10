# 고정 보컬 악보 경로 v1

`vocal_lead_v1`은 곡별 모델·preset 교체 없이 다음 순서로 실행하는 개인/비상업 검증 경로다. 출시 기본값이나 최소 수정 악보 품질로 승인하지 않았다.

1. 원음 전체 → 고정 SheetSage2/MERT → 박자·키·코드·구조 및 raw 출력 보존.
2. 같은 음원 → stereo PCM16/44.1kHz 전처리 → 고정 htdemucs, CPU/seed 0/threads 4/shifts 0 → float32 보컬·반주.
3. 분리 보컬 → 고정 YourMT3+ YPTF.MoE+Multi (noPS), CPU/seed 0/threads 2 → raw MIDI. 다중 파트는 독립 파형 근거로 선택하며 모호하면 실패한다. SheetSage2의 보컬 예측이 비어 있어도 구조 관측이 유효하면 이 단계는 진행한다.
4. 선택 보컬 → 관측된 sixteenth grid에 시간 겹침으로 배치 → Vocal MusicXML. 짧은 이벤트 누락과 원본 이벤트 대응을 `interpretation.json`에 남긴다. 음높이를 자동 보정하지 않는다.
5. MusicXML → 재생 MIDI가 배치한 모든 음표의 pitch 및 onset/offset(2ms)을 보존하는지 확인한다. 실패하면 작업을 완료하지 않는다. 성공은 원곡 정확도 판정이 아니다.
6. 기존 Job → Song → revision → 명시적 PDF/MIDI/MusicXML export 경로를 사용한다. 선택 분리음은 가사 요청에도 재사용하며, 기존 반주 코드·박자 관측을 MIDI 휴리스틱으로 덮어쓰지 않는다.

체크포인트 SHA와 정확한 라이브러리 버전은 [fixed_lead_recipe.py](../src/audio_score_tool/fixed_lead_recipe.py)에 고정돼 있다. 준비된 다른 모델로 자동 대체하거나 누락된 가중치를 자동 다운로드하지 않는다. Demucs는 정확한 로컬 모델 bag과 전체 SHA를 먼저 확인하고 `weights_only=True` 및 제한된 legacy metadata 타입만 사용한다.

## 개발 실행 환경

Python 3.12+ 제품 프로세스와 Python 3.11 모델 프로세스 둘을 구분한다. 모델 환경은 다음 두 개이며 GPU/MPS를 자동 선택하지 않는다.

- **구조:** torch/torchaudio 2.8.0, transformers 4.45.2, numpy 1.24.3, soundfile 0.14.0 및 공식 고정 SheetSage2 의존성.
- **보컬·분리:** torch/torchaudio 2.7.1, transformers 4.44.2, mt3-infer 0.2.0, numpy 2.4.6, soundfile 0.14.0. Demucs 4.0.1과 고정된 julius/openunmix/einops/omegaconf가 같은 환경에 있다. 재현 가능한 CPU 실측 환경의 버전이며, 다른 플랫폼 배포 승인을 뜻하지 않는다.

`fixed_lead_snapshot`은 다음 로컬 파일들을 가진다. weights를 공개 저장소나 CI artifact로 올리지 않는다.

```text
snapshot/
  sheetsage2/model/    # 공식 고정 model 코드·config·model.safetensors
  sheetsage2/mert/     # 공식 고정 MERT 코드·config·model.safetensors
  checkpoints/yourmt3/mc13_256_g4_all_v7_mt3f_sqr_rms_moe_wf4_n8k2_silu_rope_rp_b36_nops/last.ckpt
  demucs/htdemucs.yaml # models: ['955717e8']
  demucs/955717e8-8726e21a.th
```

설정 API 또는 동일한 `AST_*` 환경 변수로 `transcription_engine=vocal_lead_v1`, `fixed_lead_snapshot`, `fixed_vocal_cmd`, `sheetsage2_cmd`, `ffmpeg_cmd`를 결속한다. `fixed_vocal_cmd`는 보컬 환경의 Python과 `src/audio_score_tool/fixed_vocal_infer.py` 경로, `sheetsage2_cmd`는 구조 환경의 Python과 `scripts/sheetsage2_infer_adapter.py` 경로다. 기존 일반 MT3 모델 선택이나 `demucs_cmd`는 이 고정 조합을 바꾸지 않는다. 일반 독립 검수용 Demucs 설정은 별도다.

파일 업로드·YouTube·재시도에서 저장된 `vocal_lead_v1` 선택을 유지한다. 이 엔진은 `lead_sheet`만 지원하며 상용 모드와 배포 앱에서는 차단한다. 생성 화면에서 모델을 임의 변경하지 않는다. 준비 확인은 명령/파일 존재 확인이며 실제 시작 시 checkpoint SHA·runtime pin을 강제한다.

## 원본 보존과 품질 한계

`structure/native`에 원래 SheetSage2 예측을, `vocal/score.mid`에 YourMT3+ 원본을, `vocal/selected.*`에 선택 결과를 보존한다. 합성한 초기 악보와 `recipe.json`, `interpretation.json`, 양쪽 runtime/출처도 Song의 SHA 검증 model evidence로 복사한다. 누락·손상 시 Job 정리를 차단한다. 파형·weights는 이 복사 whitelist에 포함하지 않으며 원음은 기존 Song 소유 보존 경로를 쓴다.

현재 알려진 품질 문제는 전주·간주의 악기 누출, 보컬/코러스 역할, sixteenth grid의 장식음·triplet 누락, 전문가 정답이 없는 코드/키/박자 정확도다. [5곡 선행 실측](research/FIVE_SONG_FIXED_VOCAL_EXPERIMENT_2026-11-10.md)의 변환 보존 성공을 원곡 정확도로 승격하지 않는다. 이 경로를 통한 실제 전곡 인수와 수정 횟수·시간, 최종 모델/출판 품질 승인은 별도 미완료다.
