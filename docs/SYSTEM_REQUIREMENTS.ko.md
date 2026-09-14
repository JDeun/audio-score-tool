# 시스템 요구사항

AudioScoreTool의 하드웨어 요구사항은 **기본 악보 workflow**와 **AI 자동 채보(AMT) 및 선택적 오디오 분석**을 구분해서 봐야 합니다.

> [!IMPORTANT]
> 아래 AMT 사양은 v1 Tier 2 실음원 benchmark가 완료되기 전의 **provisional(잠정) 기준**입니다. 실제 stable release의 지원 사양은 Golden Set에서 측정한 처리시간(real-time factor), peak RAM/VRAM, 실패율을 바탕으로 확정합니다.

## 지원 플랫폼

현재 Desktop Packages CI는 다음 플랫폼에서 패키징과 packaged-sidecar smoke를 검증합니다.

- Windows x86_64
- macOS Apple Silicon (arm64)
- Linux x86_64

공식 signed stable installer의 최종 지원 범위는 release acceptance에서 확정합니다. Windows on ARM, Intel Mac, Linux 배포판별 호환성은 별도 검증 없이 공식 지원으로 간주하지 않습니다.

## 한눈에 보는 권장 사양

| 등급 | CPU | 메모리 | GPU | 저장공간 여유 | 적합한 사용 |
|---|---|---:|---|---:|---|
| 최소 | 64-bit 4코어급 | 8 GB | 필수 아님 | 10 GB+ | MusicXML/MIDI 편집, 미리보기, PDF/MIDI/MusicXML export |
| 권장 | 현대적 6~8코어급 | 16 GB | Apple Silicon 또는 NVIDIA GPU 8 GB VRAM+ 권장 | 20~30 GB+ | 일반적인 AMT, OMR, YouTube ingest, 중간 규모 AI component |
| 고품질 AMT 권장 | 현대적 8코어급 이상 | 32 GB | NVIDIA 12 GB VRAM+ 또는 충분한 Apple Silicon unified memory | 30~50 GB+ | MuScriptor large, 긴 full-mix 음원, Demucs/WhisperX 병용 |
| 작업용 상위 구성 | 고성능 8~16코어급 | 32~64 GB | NVIDIA 16 GB VRAM+ 또는 동급 가속 환경 | 50 GB+ NVMe SSD | 반복/대량 처리, 여러 AI 단계 연속 실행, 향후 고급 기능 |

이 표의 GPU 기준은 **앱 실행 가능 여부가 아니라 AI 처리 성능을 위한 권장값**입니다. 기본 악보 workflow는 전용 GPU가 없어도 동작하는 것을 제품 계약으로 합니다.

## 1. 기본 앱: GPU가 필요하지 않은 영역

다음 핵심 workflow는 AMT 모델을 실행하지 않으므로 전용 NVIDIA GPU를 최소 요구사항으로 두지 않습니다.

```text
MusicXML / MXL / MIDI import
        ↓
preview / edit / validate
        ↓
layout / revision / library
        ↓
MusicXML / MIDI / vector PDF export
```

이 경로에서는 CPU, 메모리, 저장장치 성능이 주된 요소입니다.

### 최소 기준

- 64-bit 4코어급 CPU
- RAM 8 GB
- 앱 및 작업 데이터용 SSD 여유 공간 10 GB 이상
- 1920×1080급 화면 권장
- 전용 GPU 불필요

RAM 8 GB는 **기본 편집/출판 workflow의 하한**으로 간주합니다. 대형 MusicXML, 많은 파트, 여러 곡 동시 작업이나 AI component 병용에는 16 GB 이상을 권장합니다.

## 2. 자동 채보(AMT)

자동 채보의 요구량은 선택한 엔진에 따라 크게 달라집니다. 모델 크기만으로 실제 VRAM 사용량을 정확히 예측할 수 없으므로 stable 지원 사양은 Tier 2 실측으로 확정합니다.

### MuScriptor

현재 개인/비상업 Quality 경로의 최우선 후보입니다.

- large: 약 1B급 이상의 대형 모델로 품질 우선
- 전용 GPU 또는 충분한 Apple Silicon unified memory를 강하게 권장
- CPU-only 실행은 가능 여부와 별개로 긴 full-mix 곡에서 실용성이 크게 떨어질 수 있음
- 잠정 권장: 시스템 RAM 32 GB, NVIDIA VRAM 12 GB+ 또는 충분한 Apple Silicon unified memory

MuScriptor 공개 weights는 CC BY-NC 4.0이므로 personal/non-commercial mode에서만 허용합니다.

### YourMT3+

상용 모드의 정확도 우선 후보이지만 release 단위 provenance 검토가 필요합니다.

- MuScriptor large보다 상대적으로 가벼운 후보
- GPU 가속 권장
- 잠정 권장: RAM 16 GB+, NVIDIA VRAM 8 GB+ 또는 Apple Silicon

### MR-MT3

속도와 작은 checkpoint를 우선하는 fallback 후보입니다.

- MT3 계열 중 상대적으로 가벼운 경로
- GPU가 있으면 처리시간이 크게 단축됨
- 저사양 시스템에서 Quality 모델보다 현실적인 선택지가 될 수 있음

엔진 선택 근거는 [`ENGINE_PERFORMANCE.ko.md`](ENGINE_PERFORMANCE.ko.md)를 참조하십시오.

## 3. Apple Silicon

Apple Silicon Mac은 CPU/GPU가 unified memory를 공유하므로 NVIDIA의 `VRAM N GB`와 일대일로 비교하면 안 됩니다.

잠정적인 제품 가이드는 다음처럼 표현합니다.

- 8 GB unified memory: 기본 악보 workflow 중심
- 16 GB: 일반 사용 및 비교적 가벼운 AMT 후보
- 24 GB 이상: AI 기능을 자주 사용하는 경우 권장
- 32 GB 이상: 대형 AMT와 여러 오디오 AI 단계를 함께 사용할 때 유리

실제 모델별 MPS 호환성, peak unified memory와 RTF는 Tier 2에서 별도 기록해야 합니다.

## 4. NVIDIA GPU / CUDA

NVIDIA GPU는 자동 채보와 오디오 AI 처리에서 가장 예측 가능한 가속 경로 중 하나입니다.

잠정 분류:

| VRAM | 권장 용도 |
|---:|---|
| 없음 | 기본 편집/출판, CPU 실행 가능한 경량 기능 |
| 4~6 GB | 경량 모델 실험. stable Quality AMT 권장 사양으로 간주하지 않음 |
| 8 GB | 일반적인 AMT 후보의 실용적 시작점 |
| 12 GB | 고품질 AMT 권장선 |
| 16 GB+ | 대형 모델, 긴 곡, 여러 AI 단계 연속 처리에 유리 |

GPU 세대, CUDA/runtime 호환성, precision, audio length에 따라 실제 메모리 사용량은 달라집니다.

## 5. 저장공간

기본 앱 자체보다 managed component와 작업 cache가 저장공간을 더 많이 사용할 수 있습니다.

공간을 사용하는 주요 항목:

- AMT model weights
- Demucs / WhisperX model
- OMR runtime
- YouTube ingest runtime
- 원본 audio와 stem
- 작업 cache
- export 결과

따라서 앱만 시험하는 경우에도 10 GB 이상, AI 기능을 본격적으로 사용하는 경우 **20~50 GB 이상의 SSD 여유 공간**을 권장합니다.

NVMe SSD는 필수 조건은 아니지만 대형 모델 load, stem/audio materialization, cache 작업에서 체감 성능에 도움이 됩니다.

## 6. 곡 길이와 처리 성능

AI 작업의 처리시간과 메모리 사용량은 다음 변수의 영향을 받습니다.

- 음원 길이
- sample rate / channel 수
- 선택 AMT 모델
- stem separation 사용 여부
- lyrics alignment 사용 여부
- CPU/GPU 종류
- GPU VRAM 또는 unified memory
- 동시에 실행하는 분석 단계 수

따라서 `GPU 8 GB = 5분 곡을 N초` 같은 고정 성능을 현재 문서에서 보장하지 않습니다.

Tier 2 Golden Set에서는 최소한 다음을 기록해 stable 요구사항을 보정합니다.

- real-time factor (RTF)
- peak system RAM
- peak VRAM / unified memory
- 곡 길이
- engine/model revision
- 실패/OOM 여부
- 최종 악보까지의 사람 편집 시간

## 7. 선택 기능별 추가 요구량

### OMR (PDF/이미지)

Audiveris 계열 OMR은 CPU와 메모리를 추가로 사용하며, stable에서 지원할 경우 필요한 JRE/runtime은 앱이 관리해야 합니다. 기본 MusicXML 편집 기능의 최소 사양을 높이는 이유로 사용하지 않습니다.

### Demucs

stem separation은 일반적인 악보 편집보다 훨씬 무거운 오디오 처리입니다. GPU가 없으면 처리시간이 크게 증가할 수 있으며, 긴 곡에서는 RAM/VRAM 사용량도 증가합니다.

### WhisperX / 가사 정렬

음성 인식·alignment model을 추가로 load하므로 AMT와 연속 실행할 경우 메모리 headroom이 필요합니다. RAM 16 GB보다 32 GB 환경이 더 안정적일 수 있습니다.

### YouTube ingest

`yt-dlp`, FFmpeg/ffprobe, JS runtime 자체는 대형 AI 모델과 같은 GPU 요구사항을 만들지 않습니다. 다운로드한 media를 AMT/Demucs 등에 넘기는 시점부터 해당 AI 요구사항이 적용됩니다.

## 8. 노트북 사용

자동 채보와 stem separation은 장시간 CPU/GPU 부하를 만들 수 있습니다.

권장 사항:

- AC 전원 연결
- OS의 저전력 모드 해제
- 충분한 냉각 확보
- SSD 여유 공간 확보
- 장시간 batch 처리 중 sleep 방지

열 제한(throttling)이 발생하면 동일 하드웨어라도 RTF가 크게 달라질 수 있습니다.

## 9. 최소 사양과 권장 사양의 의미

**최소 사양**은 모든 AI 기능을 쾌적하게 사용할 수 있다는 의미가 아닙니다.

- 최소 사양: 기본 앱의 핵심 편집/출판 workflow를 실행하기 위한 하한
- 권장 사양: 일반적인 AI-assisted workflow까지 고려한 현실적인 목표
- 고품질 AMT 권장: Quality 모델과 긴 full-mix 곡을 주요 사용 사례로 삼는 경우

지원 사양보다 낮은 시스템에서도 일부 기능이 실행될 수 있지만, 처리시간 증가나 OOM 가능성이 있는 환경을 공식 권장 사양으로 표현하지 않습니다.

## 10. stable v1에서 확정해야 할 항목

P0 Tier 2 benchmark와 P2 clean-machine acceptance가 완료되면 이 문서의 잠정값을 실측값으로 교체합니다.

최종적으로 고정할 항목:

1. 지원 Windows/macOS/Linux 버전
2. 지원 CPU architecture
3. 기본 앱 peak RAM
4. 엔진별 peak RAM/VRAM
5. 엔진별 RTF 분포
6. 대표 3~5분 곡 처리시간 범위
7. CPU-only fallback의 공식 지원 여부
8. Apple Silicon 최소 unified memory
9. NVIDIA 최소/권장 VRAM
10. managed component 전체 설치 시 필요한 디스크 용량
11. OOM/저메모리 UX와 fallback 정책

실측 전에는 provisional 값을 공식 성능 보장치로 사용하지 않습니다.

---

관련 문서:

- [`INSTALLATION.ko.md`](INSTALLATION.ko.md) — 설치 및 첫 실행 계약
- [`ENGINE_PERFORMANCE.ko.md`](ENGINE_PERFORMANCE.ko.md) — AMT 엔진 선택과 성능 근거
- [`DEPENDENCIES.ko.md`](DEPENDENCIES.ko.md) — managed component 정책
- [`ADVERSARIAL_VALIDATION.ko.md`](ADVERSARIAL_VALIDATION.ko.md) — 안정화/검증 범위
