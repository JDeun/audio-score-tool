# 앱 관리형 런타임 아티팩트 준비 절차 (출시 승인 전)

이 문서는 #29의 Windows/macOS/Linux별 실제 아티팩트를 **라이선스와 출처가 검토되기 전에는 게시하지 않는** 작업 절차를 정의합니다.

## 1. 로컬 아카이브 후보 생성

공식 출처와 배포 조건을 확인한 다음 로컬 Windows/macOS/Linux 아카이브를 준비합니다. AudioScoreTool의 개발 도구는 로컬 아카이브의 SHA-256, 안전한 압축 해제, 실행 도구 상대 경로 및 설치 상태를 자체 app-data와 분리된 임시 디렉터리에서 검사할 수 있습니다.

```bash
uv run --frozen python scripts/prepare_managed_artifact_candidate.py \
  --component youtube_runtime \
  --target windows-x86_64 \
  --version REVIEWED-VERSION \
  --archive /absolute/path/to/reviewed-youtube-runtime.zip \
  --archive-format zip \
  --url https://YOUR-REVIEWED-HTTPS-ASSET-URL \
  --tool yt-dlp=bin/yt-dlp.exe \
  --tool deno=bin/deno.exe \
  --tool ffmpeg=bin/ffmpeg.exe \
  --tool ffprobe=bin/ffprobe.exe \
  --license 'REVIEWED-LICENSE-IDENTIFIERS' \
  --provenance 'PINNED-UPSTREAM-AND-LOCAL-BUILD-RECORD' \
  --upstream-revision REVIEWED-UPSTREAM-REVISION \
  --output /tmp/youtube-windows-candidate.json
```

위 값은 **명령 형식을 보여 주는 자리표시자**입니다. URL·버전·라이선스·업스트림 리비전을 실제로 확인한 값으로 바꾸기 전에는 실행 결과를 배포 승인이나 실사용 가능 증거로 간주하지 않습니다. `yt-dlp`, `deno`, `ffmpeg`, `ffprobe` 등은 실제 아카이브에 모두 있어야 합니다.

도구가 허용하는 component 이름은 `transcription_engine`, `youtube_runtime`, `audiveris`, `whisperx`, `audio_validation`뿐입니다.

## 2. 후보 파일의 의미

출력되는 JSON은 실제 릴리스 카탈로그가 아니라 **검토용 candidate + 로컬 검사 기록**입니다.

- `candidate.redistribution_status`는 언제나 `pending`입니다. CLI는 법적 검토를 통과시킬 수 없습니다.
- `candidate.artifacts[target].sha256`은 **로컬 파일의** 해시입니다. 나중에 공식 HTTPS URL로 업로드한 실제 바이트와 일치하는지는 별도 검증해야 합니다.
- `local_validation.tool_sha256`은 안전하게 압축 해제된 도구 파일의 로컬 해시입니다.
- ZIP/TAR/RAW의 위험한 경로, 링크, 손상, 누락된 도구는 기존 `managed_components.py`의 설치·무결성 규칙으로 거부됩니다.
- CLI는 **네트워크 다운로드나 도구 실행을 하지 않습니다.** `remote_artifact_verified`, `tools_executed`, `clean_machine_verified`는 항상 `false`입니다.
- 번들 `src/audio_score_tool/managed-component-catalog.json`을 자동 갱신·덮어쓰지 않습니다.

## 3. HTTPS 배포 파일의 실제 바이트 확인 (승인 대기 증빙)

로컬 후보를 생성했다고 해서 해당 URL에 **실제로 같은 ZIP/실행 파일이 게시됐다는 뜻은 아닙니다.** 배포 담당자가 출처·저작권 조건을 검토하여 업로드한 아티팩트에만 아래 명령을 사용합니다.

```bash
# 기본값: 후보 메타데이터만 확인, 네트워크 없음
uv run --frozen python scripts/verify_managed_artifact_publication.py \
  /private/youtube-windows-candidate.json

# 명시적 --fetch 지정 시에만 해당 HTTPS URL에서 배포 바이트를 수신
uv run --frozen python scripts/verify_managed_artifact_publication.py \
  /private/youtube-windows-candidate.json \
  --fetch \
  --local-archive /private/youtube-windows-reviewed.zip \
  --output /private/youtube-windows-remote.pending.json
```

검증기는 다음 모두를 실제 설치 루틴과 공유합니다.

- 후보의 component·platform·tool mapping, upstream revision, operator-reviewed license 문자열, local SHA-256과 미승인(`pending`) 상태를 먼저 검사합니다.
- 지정된 공개 HTTPS 아티팩트를 크기 제한 내에서 스트리밍 수신하고 원래 로컬 후보의 archive SHA-256와 재대조합니다. `--local-archive`를 지정하면 해당 파일도 다시 해시합니다.
- 실제 다운로드 바이트를 별도의 임시 앱 관리 루트에 설치하여 안전한 압축 해제와 **모든 도구 SHA-256**를 검증합니다.
- 완료된 보고서에는 URL 원문/바이너리/임시 경로를 넣지 않고 URL의 해시, archive SHA-256/크기, 도구별 SHA-256와 확인 시각을 기록합니다.
- 다운로드/아카이브/도구가 서로 다르거나 검증이 실패하면 성공 보고서가 생성되지 않습니다.
- 보고서는 반드시 `redistribution_status=pending`, `approval_required=true`, `tools_executed=false`, `clean_machine_verified=false`로 유지됩니다. **재배포 승인, 서명, 원격 URL 불변성, 상용 모델 사용권, clean-machine 실동작은 별도의 검토 단계입니다.**
- `managed-component-catalog.json`에 자동으로 아티팩트를 추가하거나 배포 상태를 승인으로 전환하지 않습니다.

로컬 체크섬은 후보 생성기에서, 실제 URL 바이트 체크섬은 이 검증기에서 별도로 획득하고 두 증거를 연결해야 카탈로그 검토 단계로 진행합니다. HTTP 리다이렉트나 잘못된 출처 정책을 우회해 임의 시스템 파일을 설치하는 도구가 아닙니다.

## 4. 실제 게시 이전 필수 검토

- [ ] 정확한 upstream version·commit·모델 weight revision·포함 라이브러리 목록/해시 확정
- [ ] Windows/macOS용 실행 파일과 runtime/JRE/FFmpeg build flags 검토, 권리 증거 저장
- [ ] 라이선스와 제3자 고지/소스 제공 의무를 배포 artifact 수준에서 검토
- [ ] 재배포 승인 절차를 별도로 완료 (`pending` → 검토된 `approved`)
- [ ] HTTPS 게시 위치의 아티팩트를 실제 다운로드하고 로컬 원본과 SHA-256 대조
- [ ] Windows/macOS clean-machine에서 app-managed 설치·복구·런타임 시작 확인
- [ ] 직접 재설치, 중단된 다운로드, checksum mismatch, 기존 설치 rollback 인수시험
- [ ] Setup Center가 실제 출고 카탈로그와 설치 상태를 정확히 표시하는지 확인
- [ ] 요구되는 real-music 평가 및 commercial 모델 선정은 별도 #34 완료 조건으로 유지

메타데이터의 `approved` 문자열만으로 실제 바이너리 설치 및 clean-machine 검증까지 수행했다고 주장하지 않습니다. 최종 릴리스에는 `scripts/check_managed_publication.py --require-ready`와 실물/법적 검증 증거가 모두 필요합니다.

자세한 신뢰 경계 및 배포 승인 요건은 [MANAGED_RUNTIME.ko.md](MANAGED_RUNTIME.ko.md), [THIRD_PARTY_LICENSES.ko.md](THIRD_PARTY_LICENSES.ko.md), [#29](https://github.com/JDeun/audio-score-tool/issues/29)을 참조하십시오.


## 5. 별도 출고 승인 기록 게이트 (#29)

원격 게시 파일 자체의 SHA-256 검증은 승인 **필요조건**일 뿐 재배포 허가를 자동으로 생성하지 않습니다. `src/audio_score_tool/managed-release-approvals.json`에는 플랫폼별 독립된 검토 기록을 두며, `check_publication()`과 Setup Center는 다음을 확인합니다.

- 최종 카탈로그 항목 전체의 SHA-256이 출고 승인 기록의 `catalog_sha256`와 일치
- `verify_managed_artifact_publication.py --fetch`가 만든 미승인 원격 바이트 증빙과 실제 URL/아카이브/도구별 SHA-256·버전·플랫폼이 일치
- 별도 사람이 승인한 제3자 라이선스 검토자, 일시, 고지 URL·고지 해시, 대응 소스 제공 위치가 기록됨

어느 하나라도 없거나 불일치하면 `published=false`이며 `POST /api/setup/install`도 409로 차단됩니다. 검증 도구나 앱이 라이선스 승인 기록을 자동 작성하지 않습니다. [관리형 런타임 출고 승인 형식](MANAGED_RELEASE_APPROVALS.ko.md)에 승인 기록과 신뢰 한계를 정리했습니다.

### MT3-Infer MR-MT3 사설 후보 ZIP (native QA → 출고 준비)

Windows/macOS frozen MR-MT3의 실제 모델 추론은 CI에서 검증됐지만, 이전 실행은 모델/실행 ZIP을 항상 삭제했습니다. 원본 체크포인트 가져오기 단계는 이제 immutable Hugging Face commit `7bd24c3e1dc26468a6a9354c0a4f174405c9bad8`와 검증된 SHA-256를 모두 고정하며, 고정 원본에 해시가 다른 체크포인트만 존재하면 네이티브 빌드를 중단합니다. Source 증빙은 JSON만 CI에 업로드합니다. 운영자가 **명시적으로 로컬 사설 폴더를 지정하는 경우에만** `verify_mt3_frozen_native.py --checkpoint-dir ... --private-candidate-dir ...`가 모델 포함 검증 완료 ZIP을 보존합니다. 저장 위치는 Git 저장소 밖이어야 하고, Github Actions에서는 이 옵션 자체를 거부합니다. 이름: `MT3-MRMT3-<target>-UNAPPROVED.zip`.

다음 단계의 후보 준비 명령(`prepare_managed_artifact_candidate.py`)에 이 ZIP을 입력할 수 있지만, 플랫폼별 실제 URL, 정확한 라이선스/서드파티 notice, upstream revision 및 별도 리뷰 증빙이 확정되기 전에는 배포 파일을 공개하지 않습니다. 사설 ZIP 내부의 `pending` metadata는 법률적 승인 또는 clean-machine acceptance가 아닙니다. 운영자는 바이너리/체크포인트 아카이브를 GitHub Actions public artifact에 추가하거나 이 단계에서 `managed-component-catalog.json` 또는 승인 JSON을 변경하지 않습니다.

## 6. MR-MT3 사설 ZIP과 실제 모델 추론 증빙의 오프라인 결속 (#29)

사설 폴더에 네이티브 모델 ZIP을 보존해도, 해당 파일이 **정확히** Windows/macOS에서 검증한 파일인지와 포함된 실행 파일·모델 weight 바이트가 일치하는지는 별도 검토해야 합니다.

새로운 `scripts/audit_mt3_private_candidate.py`는 네트워크 접근 없이 사설 ZIP의 SHA-256, 정확히 3개의 허용된 ZIP 멤버(플랫폼별 `bin/mt3-infer[.exe]`, `checkpoints/mr_mt3/mt3.pth`, `provenance/frozen-native-qa.pending.json`), 각 멤버의 SHA-256, 무압축/일반 파일 속성 및 내부 pending provenance를 확인합니다. 앞서 `verify_mt3_frozen_native.py --private-candidate-dir`가 같은 실행에서 작성한 **`--output`의 실제-model QA 영수증**과 아카이브 전체/실행 바이너리/체크포인트/플랫폼/실제 추론 결과를 대조합니다. 체크포인트를 `torch.load`하지 않으며 실행 파일을 추출·실행하지 않습니다.

```bash
uv run --frozen python -m scripts.audit_mt3_private_candidate \
  --archive /private/release-review/MT3-MRMT3-macos-aarch64-UNAPPROVED.zip \
  --native-proof /private/release-review/mt3-native.pending.json \
  --output /private/release-review/mt3-model-audit.pending.json
```

이 감사 영수증을 얻기 전에는 **Windows/macOS의 `transcription_engine` 출고 후보를 새로 만들 수 없습니다**. 후보 준비 시에는 다음처럼 `--native-audit`가 필수이며, 실물 ZIP SHA-256와 설치된 CLI SHA-256를 다시 대조합니다. 현재 확인된 MR-MT3 모델 한 종류만 지원하고, 다른 모델은 별도 QA 규격/리뷰를 구현해야 합니다.

```bash
uv run --frozen python -m scripts.prepare_managed_artifact_candidate \
  --component transcription_engine \
  --target macos-aarch64 \
  --version ACTUALLY-REVIEWED-RELEASE-VERSION \
  --archive /private/release-review/MT3-MRMT3-macos-aarch64-UNAPPROVED.zip \
  --archive-format zip \
  --url https://REVIEWED-ARTIFACT-ORIGIN/REVIEWED-FILENAME.zip \
  --tool mt3-infer=bin/mt3-infer \
  --license ACTUALLY-REVIEWED-LICENSE-IDENTIFIER \
  --provenance ACTUALLY-REVIEWED-SOURCE-AND-BUILD-EVIDENCE \
  --upstream-revision ACTUALLY-PINNED-SOURCE-COMMIT \
  --native-audit /private/release-review/mt3-model-audit.pending.json \
  --output /private/release-review/mt3-publication-candidate.pending.json
```

Windows에서는 `--target windows-x86_64` 및 `--tool mt3-infer=bin/mt3-infer.exe`를 지정합니다. 위 `REVIEWED` 표기는 **실제 배포가 가능한 값이 없음을 설명하는 예시**일 뿐이며, 지금 이 명령을 그대로 실행해 승인·게시하면 안 됩니다. 정확한 원본 Git commit/revision, 라이선스, 대응 소스 및 고지 위치는 별도 사람이 독립 검토해야 합니다.

감사 보고서에는 확인된 SHA-256·빌더 버전/실제 추론 계수와 아래 **미해결 blocker**가 포함됩니다: 모델의 상용 재배포 권한, 고정 upstream 소스, frozen 의존성의 완전한 SBOM, transitive licenses/third-party notices/소스 제공, 실제 HTTPS 게시 및 독립 승인, clean-machine 설치, Tier 2 baseline 및 서명·공증·업데이트. 빌더 패키지 몇 개의 고정 버전만으로 완전한 frozen SBOM을 증명했다고 표시하지 않습니다. 모든 결과는 `redistribution_status=pending`, `publication_ready=false`이며 **독립적인 서명·법적 승인 증명서가 아닙니다**.

모델 ZIP, 실제 음원/악보 및 민감한 경로는 결과 JSON에 포함하지 않으며, CLI는 기존 파일을 덮어쓰거나 저장소 내 경로로 감사 보고서를 기록하지 않습니다. GitHub Actions에는 synthetic fixture 테스트만 실행하며 실제 모델/실행 파일은 그대로 업로드하지 않습니다.
## 7. Frozen MT3 런타임 의존성 인벤토리와 라이선스 사전 감사 (#29)

`scripts/collect_mt3_frozen_inventory.py`는 `verify_mt3_frozen_native.py`가 **실제로 만든 PyInstaller onefile 실행 파일**에서 CArchive 구성 항목의 이름/타입/압축 여부/크기와 내장 PYZ Python 모듈 목록, 네이티브 binary entry 목록을 수집합니다. 이것은 `pip list`나 설치된 패키지 목록의 단순 전사가 아니라 **최종 frozen 바이너리 내부의 TOC 스냅샷**입니다. 전체 실행 파일 SHA-256과 해당 인벤토리의 canonical JSON SHA-256이 네이티브 검증 `*.pending.json` 및 사설 ZIP의 `provenance/frozen-native-qa.pending.json`에 서로 결속됩니다.

빌더의 `importlib.metadata`에서 추가로 설치 Python distribution 이름/버전, `License-Expression`, legacy `License`, license classifiers, 존재하는 `.dist-info` LICENSE/COPYING/NOTICE 파일의 SHA-256를 수집합니다. 라이선스 전문/모델 가중치/실제 실행 바이너리를 공개 증빙으로 복사하지 않습니다. 메타데이터가 부족한 패키지는 `missing_license_metadata_names`에 표시합니다.

**범위 구분 및 미확정 사항**

- PyInstaller TOC: 최종 실행 파일 안의 *entry 이름·크기·모듈·라이브러리 후보* 증빙입니다. 바이너리 파일별 서명, 동적 로딩, 외부 시스템 라이브러리의 완전한 dependency closure 및 각각의 실제 소스 라이선스를 자동 확인하는 기능은 아닙니다.
- 빌더 설치 distribution: 빌드 머신의 metadata **전체**이지, frozen 앱에 실제 포함된 의존성의 정확한 집합이나 완전한 SBOM이 아닙니다. 빌드 전용 패키지가 포함될 수 있습니다.
- 파일의 license 문자열/notice SHA는 **법적 승인**이 아니며, 포함된 정적/동적 코드, C/C++ dependencies, 모델 가중치의 저작권·상용 재배포·고지·소스 제공 의무는 담당자가 파일별로 독립 검토해야 합니다.
- 현재 출력에는 항상 `inventory_is_complete_distributable_sbom=false`, `native_library_dependency_closure_independently_verified=false`, `third_party_license_approval=false`와 `redistribution_status=pending`이 포함됩니다.

사설 후보 감사 `scripts/audit_mt3_private_candidate.py`는 원본 네이티브 QA 영수증의 인벤토리 SHA-256을 재계산하고, 사설 ZIP provenance에 들어 있는 인벤토리 SHA와 대조합니다. 후보 준비 도구 `prepare_managed_artifact_candidate.py`는 해당 감사 영수증의 인벤토리 결속을 다음 pending 후보에 인계합니다. 단독 JSON은 제3자가 서명한 attestation이 아니므로, 이후 재배포 승인·HTTPS 게시/재다운로드·clean-machine 테스트와 혼동하지 않습니다.

CI에는 사설 모델 가중치·실행 바이너리·ZIP을 업로드하지 않고 **인벤토리가 포함된 메타데이터 JSON만** 남깁니다. 이 CI에서 증빙을 확보한 것만으로 `managed-component-catalog.json`의 artifact나 `managed-release-approvals.json`의 승인 항목을 채울 수 없습니다.
## 8. MT3 frozen 의존성 실측 분류 및 제3자 라이선스 검토 큐 (#29, 2026-11-08)

Windows/macOS에서 실제 MR-MT3 추론에 성공한 [네이티브 CI #148 증빙](https://github.com/JDeun/audio-score-tool/actions/runs/42453842931)의 **metadata-only pending JSON 두 개**를 분석했습니다. CLI `scripts/triage_mt3_frozen_dependencies.py`는 이 JSON들의 기존 SHA-256 증빙을 재검증하고, PyInstaller의 `BINARY` typecode를 실제 네이티브 DLL/공유 라이브러리로 잘못 집계하지 않도록 파일명 기준 후보 목록과 라이선스 검토 작업 항목을 분리합니다.

| 항목 | Windows x86_64 | macOS ARM64 |
|---|---:|---:|
| PyInstaller CArchive `BINARY` typecode 항목 | 5,905 | 337 |
| 확장자/파일명상 네이티브 실행 파일·공유 라이브러리 **후보** | 341 | 333 |
| `BINARY` typecode지만 위 후보가 아닌 자료·소스 등 | 5,564 | 4 |
| 빌더의 Python 배포 패키지 메타데이터 | 74 | 73 |
| SPDX `License-Expression` 없는 빌더 배포 패키지 | 43 | 40 |
| 로컬 `.dist-info` LICENSE/NOTICE 해시가 없는 패키지 | `tokenizers` | `tokenizers` |

실측 수치와 두 플랫폼의 원본 영수증·내부 인벤토리·실행파일 SHA-256는 [`release/review/mt3-native-third-party-pending-2026-11-08.json`](../release/review/mt3-native-third-party-pending-2026-11-08.json)에 고정했습니다. 원본 GitHub Actions 아티팩트가 만료되더라도 **그 당시의 관찰값을 재현 가능한 출처 식별자와 함께 보존**하는 pending 기록이며, 새 native 빌드 결과에 그대로 적용할 수는 없습니다.

**주의:** 이 수치는 PyInstaller 아카이브 TOC의 filename/typecode 분류이며 PE/Mach-O 매직·디스어셈블·OS 로더 종속성을 검사한 완전한 네이티브 SBOM이 아닙니다. Windows는 PyInstaller가 `.py` 소스와 일부 실행 속성 데이터도 `b` typecode로 포함해 기존 `native_binary_entry_count=5905`라는 *역사적 필드 이름이 잘못된 인상*을 주었습니다. 이 보고서에서는 해당 수치를 명시적으로 `pyinstaller_binary_typecode_entry_count`로 취급하며, `recognizable_native_library_filename_count`만 별도 후보 수로 기록합니다.

`tokenizers`는 빌더 메타데이터에 Apache 관련 license classifier가 있지만 해당 설치본의 로컬 notice SHA가 확인되지 않은 상태입니다. 이는 **누락된 로컬 메타데이터·검토 필요**를 뜻하며 재배포 위반이나 무라이선스임을 뜻하지 않습니다. SPDX 표현식 미기록 또한 legacy license/classifier가 별도로 존재할 수 있으므로 무허가로 단정하지 않습니다. 각 패키지의 실제 포함 여부, wheel/원본 source commit, 해당 버전 LICENSE 및 notice, 네이티브 바이너리의 정적/동적 라이브러리 provenance와 대응 소스 제공 의무를 별도로 확인해야 합니다.

기존 CI 아티팩트의 ZIP에서 `MT3-FROZEN-NATIVE-QA-windows-x86_64.pending.json` 및 `MT3-FROZEN-NATIVE-QA-macos-aarch64.pending.json`를 **사설 검토 위치에만** 추출한 뒤 다음을 실행합니다.

```bash
python -m scripts.triage_mt3_frozen_dependencies \
  --windows-proof /private/review/MT3-FROZEN-NATIVE-QA-windows-x86_64.pending.json \
  --macos-proof /private/review/MT3-FROZEN-NATIVE-QA-macos-aarch64.pending.json \
  --output /private/review/mt3-native-license-triage.pending.json
```

출력에는 경로 그룹별 네이티브 라이브러리 파일명 **후보**와 OS별 빌더 패키지 license expression/legacy label/classifiers/notice SHA 목록, 정확한 출처 체크섬, 플랫폼 간 패키지 버전 차이, 검토 우선순위가 포함됩니다. 원본 모델/바이너리/zip 바이트는 불러오거나 업로드하지 않습니다. 결과는 `publication_ready=false`, `complete_sbom_verified=false`, `redistribution_status=pending`이므로 배포 승인을 자동 활성화할 수 없습니다.

**현재 검토 순서:** PyTorch `torch/lib` 및 기타 네이티브 라이브러리의 실제 bundled 소스/동적 의존성을 추적 → `tokenizers` 고지·대응 소스 확인 → Windows BINARY typecode로 동봉된 소스/자산의 권리 목록 확보 → MR-MT3 checkpoint의 고정 upstream revision과 권리 확인 → 독립 법적 승인 및 clean-machine 재설치 검증. `main`의 catalog/approval 파일은 이 과정을 완료하기 전까지 그대로 비워 둡니다.

## 9. Frozen 네이티브 파일과 wheel RECORD의 정확한 경로 비교 (#29)

이제 `scripts/map_mt3_frozen_file_owners.py`가 Windows x86_64/macOS arm64 **최종 PyInstaller CArchive의 라이브러리 파일명 후보**와 동일 빌드에 설치된 Python wheel의 `RECORD` 상대 경로를 직접 비교합니다. 비교 결과는 `scripts/collect_mt3_frozen_inventory.py`의 SHA-256 결속된 인벤토리에 `native_file_record_hints`로 포함되며, `triage_mt3_frozen_dependencies.py` 검토 큐에 이어집니다.

`single_record_path_match`는 정확히 하나의 빌더 패키지 RECORD 경로와 일치한다는 뜻이고, `ambiguous`는 둘 이상이 같은 경로를 주장한다는 뜻이며, `unmatched`는 일치하는 RECORD가 없다는 뜻입니다. Windows에서는 상대 경로를 정규화하고 대소문자를 구분하지 않습니다. 절대/상위 디렉터리 기록이나 중복 RECORD는 독립적인 출처 단서로 삼지 않습니다. wheel `RECORD`에 SHA-256와 파일 크기가 있으면 그 **빌더 파일의 기록 메타데이터**도 보존합니다.

**이 결과는 법적 출처 소유권의 확정이 아닙니다.** PyInstaller가 바이너리를 수집하면서 경로를 이동하거나 파일을 수정할 수 있고, 같은 wheel이 포함한 네이티브 라이브러리의 별도 C/C++ 라이선스 조건도 존재합니다. 번들 안의 실제 바이너리 SHA가 wheel RECORD 해시와 동일한지 이 단계에서 실행·추출·비교하지 않으며, 동적 로더의 의존성도 완전하게 재귀 조사하지 않습니다. `source_owner_independently_verified=false`, `binary_payload_equals_record_hash_verified=false`, `license_independently_approved=false`를 유지합니다.

검토자는 일치 항목부터 실제 패키지 wheel과 포함 바이너리의 소스 라이선스를 확인하고, 미일치·복수 후보를 더 높은 우선순위로 처리할 수 있습니다. 이전 CI의 인벤토리에는 `native_file_record_hints` 필드가 없으므로, 구버전 증빙을 분석할 때는 `wheel_record_mapping_available=false`로 표시하며 **미검증을 0건으로 오인하지 않습니다**. 정식 publish 승인, 완전한 SBOM, 모델 재배포 권한, clean-machine 인수시험은 여전히 독립 조건입니다.


### Windows/macOS 실물 wheel RECORD 경로 일치 결과 (#150, 2026-11-08)

실제 [MR-MT3 native QA run #42459748293](https://github.com/JDeun/audio-score-tool/actions/runs/42459748293)에서 최종 frozen 바이너리로부터 출처 후보를 수집한 결과:

| 검토 항목 | Windows x86_64 | macOS ARM64 |
|---|---:|---:|
| 라이브러리 **파일명 후보** | 341 | 333 |
| 설치된 wheel RECORD 상대 경로에 **유일하게 일치** | 269 | 270 |
| 복수 RECORD에서 동일 경로 주장 | 0 | 0 |
| RECORD 경로 일치 없음 | 72 | 63 |

SHA-256로 식별한 CI 원본 증빙과 패키지별 일치 건수는 [메타데이터-only 원본 관찰 기록](../release/review/mt3-native-wheel-record-hints-pending-2026-11-08.json)에 고정했습니다. 일치 항목은 여전히 **파일명 기반 후보**일 뿐 실제 번들 바이너리와 wheel 원본 파일의 SHA-256이 같다는 의미가 아닙니다. 미일치 항목에는 Python 런타임 자체의 확장 모듈과 OS 라이브러리가 포함되어 있으므로, 단순히 wheel 소유 패키지를 추정해 승인해서는 안 됩니다. 2개 OS 검증 모두 `redistribution_status=pending`이며 실제 외부 바이너리/모델은 증빙으로 게시하지 않았습니다.
