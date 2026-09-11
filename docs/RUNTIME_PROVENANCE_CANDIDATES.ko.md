# v1 Runtime Provenance Candidates

이 문서는 v1 managed runtime에 넣을 **후보 구성요소의 현재 확인 상태**를 기록합니다. 법률 자문이 아니며, 이 문서에 후보로 기록되었다는 사실만으로 `managed-component-catalog.json`에 publish하지 않습니다.

실제 catalog artifact는 정확한 release/version/revision, platform별 URL, SHA-256, archive layout, license notice가 모두 확정된 뒤에만 추가합니다.

## 상태 정의

- `candidate`: 기술/라이선스 검토를 계속할 수 있음
- `conditional`: 배포 형태나 build option에 따라 조건이 달라짐
- `blocked`: 현재 정보로 commercial default에 넣으면 안 됨
- `pending-tier2`: 라이선스 경계는 검토 가능하지만 품질 baseline은 Tier 2 결과가 필요함

## AMT

### MT3-Infer 0.2.0

상태: `candidate`, `pending-tier2`

- AudioScoreTool 현재 Python extra가 `mt3-infer[torch]==0.2.0`으로 고정되어 있음
- MT3-Infer 자체는 MIT
- upstream이 MR-MT3, MT3-PyTorch, YourMT3를 서로 다른 provenance/license로 명시함
- checkpoint는 package에 포함하지 않고 runtime에 다운로드하는 구조
- MR-MT3 checkpoint는 upstream downloader에서 SHA-256 검증을 수행한다고 문서화됨
- YourMT3/MT3-PyTorch checkpoint는 provenance hash는 기록되지만 upstream downloader의 hash enforcement가 동일하지 않을 수 있으므로 AudioScoreTool managed installer가 자체 SHA-256을 반드시 검증해야 함

Release 원칙:

1. `mt3-infer`라는 wrapper license만 보고 model을 승인하지 않음
2. backend/checkpoint마다 별도 provenance를 고정
3. AudioScoreTool catalog에는 우리가 실제 다운로드하는 artifact의 SHA-256을 기록

### MR-MT3

상태: `candidate`, `pending-tier2`

- upstream implementation: MIT
- 현재 MT3-Infer provenance에서 MR-MT3 backend를 MIT로 식별
- 공개 Hugging Face MR-MT3 model repository에도 MIT license metadata가 표시됨

단, v1 commercial baseline 확정은 #34 Tier 2 품질 결과와 **정확한 checkpoint 파일/revision/hash** 확인 후 수행합니다.

### YourMT3 / YourMT3+

상태: `candidate`, `pending-tier2`, checkpoint 재확인 필요

- MT3-Infer는 vendored YourMT3 implementation을 Apache-2.0으로 식별
- 실제 v1에서 사용할 checkpoint는 `YPTF.MoE+Multi (noPS)` 등 정확한 이름/revision으로 고정해야 함
- source license와 checkpoint/model artifact license를 동일하다고 추정하지 않음

따라서 정확한 checkpoint repository/revision/license metadata를 release artifact 기준으로 재검증하기 전에는 catalog를 publish하지 않습니다.

### MT3-PyTorch backend

상태: `blocked` for commercial baseline

MT3-Infer upstream 자체가 vendored MT3-PyTorch 코드에 대해 upstream license가 선언되지 않았다고 명시합니다. 따라서 별도의 권리 확인이 없는 한 v1 commercial default 후보에서 제외합니다.

## YouTube ingestion

v1의 packaged YouTube 기능은 **하나의 self-contained managed component**로 취급합니다. release readiness가 요구하는 tool map은 다음과 같습니다.

```text
yt-dlp
deno
ffmpeg
ffprobe
```

packaged build에서는 사용자의 PATH에 있는 도구로 fallback하지 않습니다. AudioScoreTool은 managed Deno의 절대 경로를 yt-dlp의 `--js-runtimes deno:<path>`에 명시적으로 전달합니다.

### yt-dlp

상태: `conditional`

- yt-dlp source repository/PyPI source distribution/wheel은 Unlicense
- 공식 README에 따르면 PyInstaller standalone executable은 포함 dependency 때문에 GPLv3+ combined work로 배포됨
- 현재 YouTube extractor는 JS challenge 처리를 위해 외부 JS runtime 사용을 전제로 하므로 runtime provenance도 함께 고정해야 함

따라서 v1에서 **공식 standalone PyInstaller binary를 무비판적으로 managed component로 복사하지 않습니다.**

우선 검토 순서:

1. packaged Python sidecar 안에서 wheel/source 형태로 실행하는 경로
2. 별도 managed executable을 쓸 경우 해당 binary의 전체 third-party license inventory 준수
3. 어느 방식이든 exact version + source + checksum 고정

YouTube 지원 여부와 콘텐츠 사용 권한/서비스 약관은 별개의 문제입니다.

### Deno JS runtime

상태: `candidate`, redistribution 확인 필요

현재 yt-dlp 공식 문서에서 Deno는 권장 JS runtime이며 `--js-runtimes deno:/absolute/path` 형태로 명시적 실행 경로를 지정할 수 있습니다. AudioScoreTool packaged runtime은 PATH 자동탐색 대신 이 방식을 사용합니다.

v1 publication 전에 다음을 고정합니다.

- Deno exact release/revision
- Windows x86_64 / macOS arm64 artifact URL
- SHA-256
- license/source notice
- redistribution decision
- yt-dlp와 실제 smoke-tested version pair

### FFmpeg / ffprobe

상태: `conditional`

FFmpeg 공식 license 문서 기준 대부분은 LGPL-2.1-or-later이며, `--enable-gpl`을 사용하면 결과 binary가 GPL-2.0-or-later 조건으로 바뀝니다. 그 밖의 external/nonfree option도 실제 build 기준으로 확인해야 합니다.

v1 권장 조건:

- 가능한 경우 LGPL-compatible build 사용
- exact FFmpeg version 고정
- `ffmpeg -buildconf` 또는 동등한 configure flag evidence를 release provenance에 보존
- `--enable-nonfree` artifact 사용 금지
- `ffmpeg`와 `ffprobe`를 동일 provenance bundle에서 제공
- platform별 binary SHA-256 고정

## OMR — Audiveris

상태: `conditional`

- 공식 Audiveris repository: AGPL-3.0
- 최근 stable release는 Windows/Linux/macOS installer를 제공
- 공식 README에 따르면 release 5.5부터 주요 OS installer에 JRE가 포함됨

AudioScoreTool에서 executable boundary로 호출하더라도 **재배포/자동 다운로드/수정 여부에 따른 AGPL 및 포함 dependency 의무를 실제 artifact 기준으로 검토**해야 합니다.

v1 선택지는 두 가지입니다.

1. Audiveris를 독립 managed component로 제공하면서 필요한 license/source 제공 의무를 충족
2. 재배포 계약이 더 단순하고 품질이 충분한 OMR backend로 교체

현재 core release contract에서는 `audiveris` launcher가 Windows x86_64/macOS arm64 artifact에 존재해야 합니다. JRE를 Audiveris distribution 내부에 포함하는 경우에도 JRE provenance/license는 artifact evidence에 함께 기록합니다.

결정 전에는 catalog의 `audiveris.artifacts`를 비워 둡니다.

## Publication rule

다음 정보가 모두 있어야 `managed-component-catalog.json`에 platform artifact를 추가할 수 있습니다.

```text
component id
version
upstream revision/tag
platform + architecture
download/source URL
SHA-256
archive type/layout
required entrypoint/tool map
license identifier
third-party notice/source obligations
redistribution_status=approved
clean-machine smoke result
```

또한 release readiness checker는 component별 required tool set이 실제 artifact manifest에 존재하는지 검사합니다.

하나라도 확인되지 않으면 Setup Center에서 `published=false`를 유지하고 v1 release gate는 fail-closed 됩니다.

## 관련 이슈

- #34 Tier 2 / commercial AMT baseline
- #29 managed runtime artifact publication
- #22 signed release acceptance
- #36 v1 readiness umbrella
