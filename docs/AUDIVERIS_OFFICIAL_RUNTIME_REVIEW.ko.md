# Audiveris/JRE 공식 런타임 후보 검증 — 재배포 승인 전

## 제품 아키텍처에서의 위치

AudioScoreTool의 PDF·PNG·JPG·TIFF·BMP 악보 가져오기 경로는
`POST /api/import/score` → 앱 소유 Audiveris 실행 파일 `-batch -transcribe -export` → MusicXML/MXL 정규화 → SQLite Song 등록 → Inspector 편집 → 명시적 Export입니다.
따라서 이 작업은 **OMR 실행 환경 검증**이며 AMT 채보 모델 품질 실험이 아닙니다.

현재 코드의 `managed-component-catalog.json`에서 `audiveris.artifacts`는 빈 객체입니다. 지원 대상의 실제 설치 가능성이 검증되기 전에는 원칙적으로 503/설치 준비 필요 상태를 유지해야 합니다. 개발자 머신에 설치된 임의 Java나 Audiveris PATH를 패키지 앱의 대체 경로로 사용하는 것은 허용하지 않습니다.

## 공식 Audiveris 5.11.0 자산 — 고정 후보

| 대상 | 공식 파일 | 원본 SHA-256 |
|---|---|---|
| Windows x86_64 | `Audiveris-5.11.0-windowsConsole-x86_64.msi` | `5f1b4e96a12c53c7da426814b76e599363c4181e291855996e0a6878dda95f71` |
| macOS ARM64 | `Audiveris-5.11.0-macosx-arm64.dmg` | `17491af8b6d40153b031dd1f0815e37213f0999ef23f10586af46706e59b2eb6` |

공식 GitHub [릴리스](https://github.com/Audiveris/audiveris/releases/tag/5.11.0)의 asset digest/size를 `release/review/audiveris-official-installer-pins-2026-11-07.json`에 기록했습니다. 공식 소스 태그 커밋은 `9e1e55cd2746037d059345881c53e6a6754bffbd`입니다. 이 값은 현재 검토 후보 고정이지 SHA가 실제 바이트와 대조됐다는 증거가 아니며, 실제 대조 결과는 별도 CI를 확인해야 합니다.

Audiveris upstream [설치 문서](https://github.com/Audiveris/audiveris/blob/5.11.0/docs/_pages/tutorials/install/binaries.md)와 [packaging](https://github.com/Audiveris/audiveris/blob/5.11.0/packaging/README.md)에 따르면 5.5 이후의 OS 설치 파일은 jlink/jpackage로 제작한 JRE를 포함합니다. 반면 **Tesseract OCR 언어 데이터는 설치 파일에 기본 포함되지 않고**, Audiveris가 실행 후 언어별 데이터를 추가로 내려받는 방식입니다. 일반 사용자에게 별도 설치를 요구하지 않는 AudioScoreTool의 정책상 이 데이터 공급과 라이선스 검토는 후속 배포 게이트입니다.

## 검증 절차

1. `scripts/verify_audiveris_official_installer.py`가 원본 MSI/DMG의 **파일 이름·크기·SHA-256·MSI OLE / DMG UDIF 매직**을 정확히 고정값과 비교합니다. 네트워크 다운로드/바이너리 실행은 하지 않습니다.
2. 별도 `.github/workflows/audiveris-official-installer-review.yml`은 Windows 2025 x64와 macOS 15 ARM64 러너에서 공식 URL의 파일을 임시 내려받고 첫 번째 검증기를 실행합니다.
3. Windows에서는 MSI administrative image를 **임시 폴더**에 추출하고, macOS에서는 DMG를 **읽기 전용** 마운트합니다. macOS 이미지에는 GNU AGPL 안내가 포함되어 있어 CI의 비대화형 읽기 전용 검토에서는 `echo Y | PAGER=cat hdiutil attach`로 표시된 안내에 한 번 응답합니다. `-agree-to-license`는 이 macOS의 `hdiutil`에서 유효한 옵션이 아닙니다. 이는 upstream 라이선스 안내를 검토 작업에 한해 처리하는 것이며, **앱·JRE·OCR 파일의 제3자 상용 재배포 승인이나 소스 제공 의무 완료를 뜻하지 않습니다.** 사용자의 Program Files/Applications로 자동 설치하거나, 이 출력물을 임의로 재패키징하지 않습니다.
4. `scripts/verify_audiveris_native_layout.py`에서 본체 launcher, 내장 `java[.exe]`, JRE의 `release` 정보를 확인한 후 절대 경로·빈 PATH로 각각 `-version`을 실행해 출시 후보 버전을 확인합니다. Windows에서 Java Swing이 참조하는 사용자 `USERPROFILE`/`APPDATA`는 정상 OS 경로를 유지합니다. 이를 임의 추출 폴더로 덮어쓰면 Windows `FileSystemView` 초기화 오류로 종료할 수 있으며, 빈 PATH의 외부 명령 차단과는 별개입니다. 이 검증이 성공하더라도 실행 중인 Audiveris 프로세스가 **반드시 해당 JRE를 사용했는지** 별도 프로세스 추적 없이 단정하지 않으며 해당 메타데이터는 false로 유지합니다.
5. CI에는 `SOURCE-EVIDENCE.pending.json` 및 `NATIVE-EVIDENCE.pending.json`만 공개 artifact로 보존합니다. 다운로드된 설치 파일·JRE·실행 파일·악보 이미지는 업로드하지 않습니다.

자세한 커맨드는 각 도구의 `--help`를 참조합니다. 로컬 원본 검증 예시:

```bash
uv run --frozen python scripts/verify_audiveris_official_installer.py \
  --target windows-x86_64 \
  --installer /absolute/review/Audiveris-5.11.0-windowsConsole-x86_64.msi \
  --output /absolute/review/SOURCE-EVIDENCE.pending.json
```

## ZIP 기반 관리형 설치·재배치 검토

[#129](https://github.com/JDeun/audio-score-tool/issues/129)의 추가 검증은 `scripts/assemble_audiveris_portable_candidate.py`에서 실행합니다. 이미 공식 SHA-256으로 검증한 MSI/DMG, `SOURCE-EVIDENCE.pending.json`, native `NATIVE-EVIDENCE.pending.json`의 **동일 원본**만 허용합니다.

1. Windows MSI의 `Audiveris/` 전체 앱 이미지 또는 macOS DMG의 `Audiveris.app/` 전체 이미지(내장 JRE·JAR/리소스 포함)를 임시 ZIP으로 묶습니다. 외부 다운로드·임의 Java 설치·추가 모델 실행은 없습니다.
2. 원본 이미지의 특수 파일·디렉터리 symlink·앱 외부로 향하는 symlink는 거부합니다. 공식 macOS app에 있는 `ADDITIONAL_LICENSE_INFO` 등 **동일 앱 트리의 regular file을 가리키는 파일 symlink만** 경계·실체·해시 확인 후 ZIP의 일반 파일로 실체화합니다. 링크를 통째로 따르거나 바깥 파일을 가져오지 않으며 실체화 개수는 보류 증거에 기록합니다. 이 변환 후에는 기존 macOS 코드 서명 검증이 유효하다고 주장할 수 없으므로 signed/notarized acceptance는 별도 유지합니다.
3. 전체 멤버 수·압축 해제 크기에 상한을 적용하고, 실행 파일의 소유자 execute bit를 ZIP에 기록합니다. 기존 `managed_components.py`는 등록된 launcher 외에 `Contents/runtime/.../bin/java` 같은 **중첩 실행 파일의 POSIX 실행 권한을 복구하도록 수정**했습니다. 위험한 SUID/SGID/쓰기 권한은 그대로 복원하지 않습니다.
4. **실제 제품 코드 `install_component_artifact(local_archive=...)`**를 격리된 임시 component root에 실행하여 ZIP 검사·무결성·state commit을 확인합니다. 이동된 `Audiveris`/JRE 실행 파일의 SHA-256을 공식 native receipt과 다시 비교하고, PATH를 비운 상태에서 각각 `-version` 실행해 이동 후 실행 가능성을 검증합니다.
5. CI의 ZIP은 러너 임시 폴더에서만 존재하며 **공개 Actions artifact로 업로드하지 않습니다**. 원본 확인서 SHA, 네이티브 확인서 SHA, ZIP SHA, launcher/JRE SHA, 설치·이동 후 기동 결과를 `*.pending.json`에만 기록합니다.

이 성공은 **로컬 설치 검증**일 뿐, ZIP의 공용 HTTPS 게시·재배포 승인·codesign/notarization·JVM 프로세스 트레이싱·GUI/텍스트 OCR 모델이 포함된 PDF→MusicXML→Song end-to-end 실행을 증명하지 않습니다. `audiveris.artifacts`는 계속 비워 둡니다.

## 실제 OMR → SQLite Song → 편집·출력 제품 인수시험

[#131](https://github.com/JDeun/audio-score-tool/issues/131)은 **실제 Audiveris 5.11.0이 MusicXML을 생성하는지** 확인하기 위한 독립적인 네이티브 인수시험입니다. 이전의 launcher `-version`/ZIP 설치 성공만으로는 OMR이 된다고 선언할 수 없기 때문입니다.

`.github/workflows/audiveris-official-installer-review.yml`의 Windows/macOS 러너에서 공식 SHA가 검증된 로컬 ZIP을 다시 실제 `install_component_artifact()`로 임시 설치합니다. `scripts/smoke_audiveris_omr_product_e2e.py`는 원본 저작권 악보나 테스트 코퍼스를 다운로드하지 않습니다.

1. 앱이 소유한 독창적인 12마디/48개 4분음표의 간단한 MusicXML을 코드로 생성합니다. **제품 내장 Verovio→fpdf2**를 사용해 이 MusicXML을 인쇄형 PDF로 만듭니다.
2. 임시 앱 데이터/SQLite와 `AST_PACKAGED=1`, 검증된 `AST_COMPONENT_DIR`, 빈 `PATH`, 테스트 전용 `AST_API_TOKEN`을 설정합니다. 운영체제의 등록된 사용자 폴더와 내장 Java는 그대로 사용합니다.
3. 실제 FastAPI의 `GET /api/omr/status`를 조회해 관리형 SHA 검증 `audiveris` 경로만 선택했는지 확인하고, 잘못된 API token은 401을 받는지 확인합니다.
4. `POST /api/import/score`에 생성한 PDF를 업로드하고 Job 완료를 최대 420초 동안 기다립니다. 실패·취소·중단·timeout은 검증 실패이며, 실패를 성공으로 대체하는 XML fixture나 모델 모킹은 사용하지 않습니다.
5. 실제 Audiveris가 만든 MXL/MusicXML을 기존 안전한 `omr.normalize_musicxml` 경로로 읽고, 유효한 MusicXML·파트·최소 4개 pitched notes를 검증합니다. `GET /api/songs`의 Job→Song 동기화로 SQLite canonical Song이 정확히 하나 등록됐고, `source_kind=omr` 및 원본 PDF managed asset이 존재하는지 확인합니다.
6. `GET /api/songs/{id}/notes`의 Inspector note ID로 실제 음정을 한 번 수정하고, `PATCH /api/songs/{id}/credits`로 제목·크레딧을 CAS 기반 한 Revision에 저장합니다. 현재 MusicXML의 영속 저장과 revision 증가를 확인합니다.
7. `POST /api/songs/{id}/export-to`에서 **MusicXML/PDF/MIDI/파트 악보**를 실제 생성하고, PDF/MIDI 바이트 및 파트 XML/PDF 쌍을 확인합니다.
8. 임시 PDF/MXL/ZIP/원본/DB는 러너 수명 내에서 정리하고, 공식 원본 후보 SHA 및 처리·편집·출력 성공 여부를 담은 **`OMR-PRODUCT-E2E.pending.json`만** Actions artifact에 추가합니다.

이 인수시험은 synthetic 음표를 많이 맞혔는지 측정하는 모델 벤치마크가 아닙니다. 실제 손글씨/스캔 악보·복잡한 레이아웃·언어별 OCR 품질과 성능은 평가하지 않으며, **AGPL/JRE/Tesseract 언어팩의 배포 승인, 공용 URL 게시, 정식 설치본에서의 OS codesigning/notarization/클린 머신 테스트**는 계속 별개입니다. `audiveris.artifacts={}` 및 `redistribution_status=pending`을 유지합니다.

## 이 검증으로 **완료되지 않는 것**

- MSI/DMG를 AudioScoreTool의 **ZIP/TAR 기반 관리형 설치기**가 바로 처리할 수 있는 것은 아닙니다. 앱 소유·버전 고정·SHA 검증이 적용된 **portable archive**, 안전한 업데이트/삭제/복구 테스트가 별도로 필요합니다.
- Windows MSI 콘솔 실행과 macOS DMG 마운트는 CI상의 **추출/실행 검토**일 뿐, 신규 사용자 컴퓨터에 설치된 AudioScoreTool 내부에서 정상 작동한다는 증거가 아닙니다.
- 실제 악보 PDF/PNG → Audiveris → MusicXML/SQLite Song → 최종 export에 대한 end-to-end acceptance는 별도 단계입니다. OMR 품질 벤치마크는 이 단계에도 포함하지 않습니다.
- Audiveris는 AGPL-3.0 계열이므로 제공하는 컴파일된 프로그램, 수정·연결 구성, source offer, 저작권 고지, 제3자 라이브러리/JRE/Tesseract data 및 배포 관계에 대한 **개별 법적 검토**가 필요합니다. 도구가 자동으로 라이선스를 승인할 수 없습니다.
- 특히 OCR 언어팩 공급 경로와 라이선스를 검토·고정하기 전에는 지원되는 텍스트·가사 OMR 기능을 완전한 오프라인 지원으로 선언하지 않습니다.
- Source release의 검증된 바이트·내장 JRE 검사만으로 소프트웨어 서명/공증·독립 upstream 서명·재현 가능한 빌드·클린 머신 검증은 완료되지 않습니다.

따라서 **이 작업의 결과는 항상 `redistribution_status=pending`**이며 `managed-component-catalog.json`을 변경하지 않습니다. 최종 출시 완료는 [#29](https://github.com/JDeun/audio-score-tool/issues/29), 서명 검증은 [#22](https://github.com/JDeun/audio-score-tool/issues/22)에서 분리 관리합니다.
