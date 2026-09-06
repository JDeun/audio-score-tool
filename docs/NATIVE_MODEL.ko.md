# AudioScore Native

AudioScore Native는 AudioScoreTool의 자체 다중 악기 자동 채보(AMT) 엔진입니다. 목적은 특정 외부 비상업 모델 가중치에 제품이 종속되지 않도록 하고, 상업 사용이 허용된 데이터로 독립 학습한 프로젝트 소유 checkpoint를 사용할 수 있게 하는 것입니다.

## 설계 원칙

1. **제품과 모델 런타임 분리**  
   데스크탑/FastAPI orchestration은 `score.mid + score.musicxml` 계약만 요구합니다.
2. **외부 비상업 가중치 비의존**  
   Native checkpoint는 별도 학습합니다.
3. **데이터 provenance 강제**  
   manifest에 명시된 라이선스가 allowlist에 없으면 학습을 거부합니다.
4. **동일한 후처리 재사용**  
   자동 코드, 가사 정렬, 파트보, MusicXML 편집, 출판 조판은 provider와 독립적입니다.

## 현재 모델 구조

```text
Audio
 ↓
Mono / Resample
 ↓
Log-Mel Spectrogram
 ↓
Conv projection ×2
 ↓
Transformer Encoder
 ↓
Autoregressive Transformer Decoder
 ↓
Music Event Tokens
 ↓
MIDI
 ↓
MuseScore quantization
 ↓
MusicXML / PDF
```

### Event vocabulary

- BOS / EOS / PAD
- 10 ms time shift
- tempo
- General MIDI program
- percussion program marker
- note-on
- note-off
- velocity bucket

이 event stream은 여러 악기 이벤트를 한 시퀀스로 표현합니다.

## 설치

```bash
uv sync --extra native
```

필수 optional dependency:

- PyTorch
- torchaudio

## 데이터 manifest

JSONL 한 줄이 한 샘플입니다.

```json
{"audio":"/data/song.wav","midi":"/data/song.mid","license":"CC-BY-4.0","split":"train"}
```

현재 허용 라이선스:

- `CC-BY-4.0`
- `CC0-1.0`
- `MIT`
- `Apache-2.0`
- `project-owned`

허용되지 않은 예:

```json
{"license":"CC-BY-NC-4.0"}
```

이 항목이 존재하면 학습을 시작하지 않습니다.

## Slakh2100 manifest 준비

저장소의 `training/prepare_slakh.py`를 사용합니다.

```bash
python training/prepare_slakh.py /path/to/slakh2100 --output manifests/slakh.jsonl
```

생성된 manifest는 실제 파일 존재 여부와 라이선스/provenance를 다시 검토한 뒤 학습에 사용해야 합니다.

## 학습

```bash
python training/train_native.py manifests/slakh.jsonl \
  --output checkpoints/audio-score-native.pt \
  --device cuda \
  --epochs 20
```

주요 옵션:

- `--batch-size`
- `--learning-rate`
- `--d-model`
- `--nhead`
- `--encoder-layers`
- `--decoder-layers`
- `--dim-feedforward`
- `--max-audio-frames`
- `--max-tokens`

validation split이 없는 소규모 pilot manifest에서는 고정 seed로 일부 데이터를 validation에 분리합니다.

## checkpoint

checkpoint 포맷:

```text
audio-score-native-v1
```

저장 항목:

- model config
- state_dict
- dataset/manifest metadata
- validation loss
- global step
- 허용 라이선스 목록

## 추론

```bash
audio-score-native transcribe song.wav \
  --checkpoint checkpoints/audio-score-native.pt \
  --output outputs/song \
  --device cuda
```

출력 계약:

```text
outputs/song/
├─ score.mid
├─ score.musicxml
└─ full_score.pdf
```

## 데스크탑 앱 연결

환경변수:

```bash
AST_TRANSCRIPTION_ENGINE=native
AST_NATIVE_ENGINE_CMD=audio-score-native
AST_NATIVE_CHECKPOINT=/absolute/path/audio-score-native.pt
```

또는 앱의 **채보 엔진** 설정에서 선택합니다.

Native checkpoint가 없거나 파일이 존재하지 않으면 preflight가 준비되지 않은 것으로 표시하고 채보를 시작하지 않습니다.

## 평가

Native 모델은 기존 benchmark 계약에 맞춰 다음 지표로 비교할 수 있습니다.

- Note Precision
- Note Recall
- Note F1
- Onset MAE
- 처리 시간
- MusicXML 렌더 성공률
- 파트 분리 품질
- 후속 코드 분석 성공률

실제 상용 모델 선택에는 synthetic/aligned dataset만이 아니라 실제 믹스 음원 도메인의 검증 세트가 필요합니다.

## 아직 외부 자원이 필요한 작업

저장소가 자동으로 대신할 수 없는 부분:

- 대규모 학습 데이터 다운로드/보관
- 데이터셋별 최종 법적/계약적 사용권 검토
- 장시간 GPU 학습
- 실제 상용 음원 검증 세트 구축
- 모델 품질 튜닝 및 checkpoint 선정

코드, 학습 루프, 라이선스 gate, checkpoint 포맷, 제품 provider 통합은 저장소에 포함됩니다.
