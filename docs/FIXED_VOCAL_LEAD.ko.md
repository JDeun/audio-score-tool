# 고정 보컬 악보 경로 v1

`vocal_lead_v1`은 곡별 모델·preset 교체 없이 다음 순서로 실행하는 개인/비상업 검증 경로다. 출시 기본값이나 최소 수정 악보 품질로 승인하지 않았다.

1. 두 runtime의 preflight 후 원음 전체 → 고정 Beat This final0/DBN(CPU/seed 0/threads 2)으로 박·첫박을 관측하고, 고정 SheetSage2/MERT로 박자표·키·코드·구조를 관측한다. 두 모델의 raw 출력은 각각 보존한다.
2. 같은 음원 → stereo PCM16/44.1kHz 전처리 → 고정 htdemucs, CPU/seed 0/threads 4/shifts 0 → float32 보컬·반주.
3. 분리 보컬 → 고정 YourMT3+ YPTF.MoE+Multi (noPS), CPU/seed 0/threads 2 → raw MIDI. 다중 파트는 독립 파형 근거로 선택하며 모호하면 실패한다. SheetSage2의 보컬 예측이 비어 있어도 구조 관측이 유효하면 이 단계는 진행한다.
4. 선택 보컬 → DBN 박과 S2의 단일 3/4 또는 4/4 박자표로 만든 sixteenth grid에 시간 겹침으로 배치 → Vocal MusicXML. 다른 박자표나 모호한 대응은 실패한다. 짧은 이벤트 누락, 외삽한 앞·뒤 박, 원본 이벤트 대응을 `interpretation.json`에 남긴다. 음높이를 자동 보정하지 않는다.
5. MusicXML → 재생 MIDI가 배치한 모든 음표의 pitch 및 onset/offset(2ms)을 보존하는지 확인한다. 실패하면 작업을 완료하지 않는다. 성공은 원곡 정확도 판정이 아니다.
6. 기존 Job → Song → revision → 명시적 PDF/MIDI/MusicXML export 경로를 사용한다. 선택 분리음은 가사 요청에도 재사용하며, 기존 반주 코드·박자 관측을 MIDI 휴리스틱으로 덮어쓰지 않는다.

체크포인트 SHA와 정확한 라이브러리 버전은 [fixed_lead_recipe.py](../src/audio_score_tool/fixed_lead_recipe.py)에 고정돼 있다. 준비된 다른 모델로 자동 대체하거나 누락된 가중치를 자동 다운로드하지 않는다. Demucs는 정확한 로컬 모델 bag과 전체 SHA를 먼저 확인하고 `weights_only=True` 및 제한된 legacy metadata 타입만 사용한다.

## 개발 실행 환경

Python 3.12+ 제품 프로세스와 Python 3.11 모델 프로세스를 구분한다. 모델 환경은 다음 세 개이며 GPU/MPS를 자동 선택하지 않는다.

- **구조:** torch/torchaudio 2.8.0, transformers 4.45.2, numpy 1.24.3, soundfile 0.14.0 및 공식 고정 SheetSage2 의존성.
- **박자:** 별도의 Python 3.11 환경. `BEAT_RUNTIME`의 정확한 버전(beat-this 1.1.0, torch/torchaudio 2.7.1, numpy 1.26.4, soundfile 0.14.0, madmom 0.17.dev0, soxr 1.1.0, scipy 1.17.1, einops 0.8.2, rotary-embedding-torch 0.8.6)을 사용한다. BeatThis 소스는 `CPJKU/beat_this@b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c`, madmom 소스는 `CPJKU/madmom@27f032e8947204902c675e5e341a3faf5dc86dae`다. madmom native extension 빌드와 pretrained weights 제거가 필요하다. 아래 설치 절차로 별도 환경을 구성한다. 시작 전 preflight가 소스 트리·native extension·가중치와 버전을 검증한다.
- **보컬·분리:** torch/torchaudio 2.7.1, transformers 4.44.2, mt3-infer 0.2.0, numpy 2.4.6, soundfile 0.14.0. Demucs 4.0.1과 고정된 julius/openunmix/einops/omegaconf가 같은 환경에 있다. 재현 가능한 CPU 실측 환경의 버전이며, 다른 플랫폼 배포 승인을 뜻하지 않는다.

### 박자 환경 설치 (macOS arm64 검증)

다음은 Python 3.11.15와 C 컴파일러가 설치된 환경에서 검증한 절차다. 새로운 빈 디렉터리에서 실행하며, 제품·보컬 환경을 공유하지 않는다. `uv`와 Git이 필요하다. 모델 저장소에서는 initializer만 복사하고 pretrained weights는 설치하지 않는다.

```sh
uv venv --python 3.11 venv
uv pip install --python venv/bin/python -r /path/to/audio-score-tool/requirements-beat-runtime.txt
git clone https://github.com/CPJKU/madmom.git madmom
git -C madmom checkout 27f032e8947204902c675e5e341a3faf5dc86dae
git clone https://github.com/CPJKU/madmom_models.git madmom_models
git -C madmom_models checkout 7e3dc1b0cad499792767074d03c38b194b9b0a79
test "$(git hash-object madmom_models/__init__.py)" = aac941443fa08ca10aad1af5e8cb9dd664d42b09
cp madmom_models/__init__.py madmom/madmom/models/__init__.py
uv pip install --no-build-isolation --no-deps --python venv/bin/python ./madmom
git clone https://github.com/CPJKU/beat_this.git beat_this
git -C beat_this checkout b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c
printf 'setuptools==80.9.0\n' > beat-build-constraints.txt
uv pip install --no-deps --build-constraint beat-build-constraints.txt --python venv/bin/python ./beat_this
venv/bin/python /path/to/audio-score-tool/src/audio_score_tool/fixed_vocal_infer.py beat-preflight ignored.wav ignored.npz --snapshot /path/to/snapshot
```

마지막 명령은 지정된 final0 체크포인트와 설치된 runtime을 검증한다. `ignored.wav`와 `ignored.npz`는 preflight에서 읽거나 쓰지 않는다. 완성된 환경의 절대 Python 경로와 adapter 경로를 `fixed_beat_cmd`로 설정한다. native 바이너리는 시스템별로 빌드되며 다른 플랫폼에서 검증됐다는 뜻은 아니다.

`fixed_lead_snapshot`은 다음 로컬 파일들을 가진다. weights를 공개 저장소나 CI artifact로 올리지 않는다.

```text
snapshot/
  sheetsage2/model/    # 공식 고정 model 코드·config·model.safetensors
  sheetsage2/mert/     # 공식 고정 MERT 코드·config·model.safetensors
  checkpoints/yourmt3/mc13_256_g4_all_v7_mt3f_sqr_rms_moe_wf4_n8k2_silu_rope_rp_b36_nops/last.ckpt
  beat-this/final0.ckpt # SHA-256 8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331
  demucs/htdemucs.yaml # models: ['955717e8']
  demucs/955717e8-8726e21a.th
```

설정 API 또는 동일한 `AST_*` 환경 변수로 `transcription_engine=vocal_lead_v1`, `fixed_lead_snapshot`, `fixed_vocal_cmd`, `fixed_beat_cmd`, `sheetsage2_cmd`, `ffmpeg_cmd`를 결속한다. `fixed_vocal_cmd`는 보컬 환경의 Python과 `src/audio_score_tool/fixed_vocal_infer.py` 경로, `fixed_beat_cmd`는 별도 박자 환경의 Python과 같은 `src/audio_score_tool/fixed_vocal_infer.py` 경로(예: `/path/to/beat-venv/bin/python /path/to/repo/src/audio_score_tool/fixed_vocal_infer.py`), `sheetsage2_cmd`는 구조 환경의 Python과 `scripts/sheetsage2_infer_adapter.py` 경로다. 기존 일반 MT3 모델 선택이나 `demucs_cmd`는 이 고정 조합을 바꾸지 않는다. 일반 독립 검수용 Demucs 설정은 별도다.

파일 업로드·YouTube·재시도에서 저장된 `vocal_lead_v1` 선택을 유지한다. 이 엔진은 `lead_sheet`만 지원하며 상용 모드와 배포 앱에서는 차단한다. 생성 화면에서 모델을 임의 변경하지 않는다. 준비 확인은 명령/파일 존재 확인이며 실제 시작 시 checkpoint SHA·runtime pin을 강제한다.

## 원본 보존과 품질 한계

`structure/native`에 원래 SheetSage2 예측을, `beat.npz`에 DBN 검출과 원시 Beat This logits를, `vocal/score.mid`에 YourMT3+ 원본을, `vocal/selected.*`에 선택 결과를 보존한다. 합성한 초기 악보와 `recipe.json`, `interpretation.json`, 각 runtime/출처도 Song의 SHA 검증 model evidence로 복사한다. 누락·손상 시 Job 정리를 차단한다. 파형·weights는 이 복사 whitelist에 포함하지 않으며 원음은 기존 Song 소유 보존 경로를 쓴다.

새 고정 경로 import는 DBN이 첫 관측 첫박 앞에 외삽한 한 박이 빈 첫 마디로 기보된 경우를 확인한다. 원본 보컬·격자·코드와 기보 정보가 모두 비어 있으면 새 악보에서 그 마디를 생략하고 첫 관측 첫박을 1마디로 표시한다. 원음 기준 첫박 시각은 MusicXML의 명시적 audio origin으로 저장하고 MIDI에도 반영한다. 생략한 원본 마디와 대응하는 첫 출력 마디의 원본 인덱스는 `notation-report.json`에 남긴다. 실제 못갖춘마디, 관측된 쉼표 마디, 끝마디와 기존 저장 악보는 보존한다.

2026-11-24 보관된 DBN 5곡 결과를 새 코드로 읽어 2,723개 수행 음표의 격자 대응과 입력 불변을 확인했다. American Idiot와 사건의 지평선만 위 조건에 해당해 첫 빈 마디가 생략됐다. 나머지 3곡의 MIDI는 기존 파일과 byte-identical이다. 두 곡의 음표/코드 상대 기보 위치는 각각 308음/297기호, 614음/233기호 모두 유지됐고, 기존 MIDI와의 최대 시각 차이는 각각 약 8.952µs/1.016µs였다. 명시적 origin의 MIDI tick 반올림과 기존 padding epsilon 범위다. 코드 경계는 padding 제거 전 원래 clock에서 투영하므로 경계 중간점의 반올림도 보존한다.

American Idiot는 새 Song의 정상 출력 함수로 PDF 5쪽·MusicXML·MIDI를 생성하고 첫 마디와 끝 쉼표 마디, 원음 시각을 검증했다. 전체 HTTP 흐름·기존 Song 자동 갱신·새 모델 추론·원곡 정확도 승인은 이 검증에 포함되지 않는다. 비공개 보고서 SHA `f13808e0a6d6edd02ed4aa3b14076c64d44ff3b091289d40bbea8d14b12e4bc2`, 모듈 경로와 5곡 재생성을 독립 확인한 집계 SHA `2811ecdb0106ed365162198c9cd6cc3df133076bd18197e1b0a4622ce11791a5`. 원음·음표/코드 trace·악보는 공개하지 않는다. 소유 예제 17개를 포함한 관련 검사 165개는 통과했으며 기존 FFmpeg 검사 1개는 로컬 환경에서 skip됐다.

현재 알려진 품질 문제는 전주·간주의 악기 누출, 보컬/코러스 역할, sixteenth grid의 장식음·triplet 누락, 전문가 정답이 없는 코드/키/박자 정확도다. [5곡 선행 실측](research/FIVE_SONG_FIXED_VOCAL_EXPERIMENT_2026-11-10.md)의 변환 보존 성공을 원곡 정확도로 승격하지 않는다. 이 경로를 통한 실제 전곡 인수와 수정 횟수·시간, 최종 모델/출판 품질 승인은 별도 미완료다.

[전체 길이 5곡 제품 재시험](research/FIVE_SONG_FIXED_PRODUCT_2026-11-10.md)은 업로드·출력·독립 검수와 삭제 후 원본 보존을 통과했다. 다만 [vocadito 40개 격자 비교](research/FIXED_GRID_VOCADITO_ABLATION_2026-11-10.md)에서 동일한 raw 음표의 onset F1은 A1 기준 0.4957→0.4383, A2 기준 0.5907→0.5231로 하락했고 1,809음 중 44음이 생략됐다. 연주 시각 기준 F1과 기보 정답은 구분하되, 이 손실을 해결·검증하기 전 최종 모델이나 기본 경로로 승격하지 않는다.

## 보컬 pitch 관측 보존

새 `pitch.npz` 관측 버전 2는 기존 threshold 적용 `times`, `hz`와 함께 원래 `raw_hz`, `periodicity`, A-weighted `loudness_db_a`를 보존한다. receipt에는 16kHz로 디코딩한 프레임 수와 hop이 있으며 전체 프레임 범위와 threshold 일치를 검증한다. periodicity는 보정된 확률이나 정답이 아니다. 기존 버전 1(버전 필드 없음 포함)은 읽을 수 있지만 raw 배열과 전체 프레임 범위는 알 수 없으며 파일을 다시 쓰지 않는다. 기존 `hz`의 0은 무음, 무성음, 근거 부족 중 무엇인지 구별하지 못한다. 이 관측은 음표를 자동으로 수정하지 않는다.
