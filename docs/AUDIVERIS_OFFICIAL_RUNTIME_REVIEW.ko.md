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

## 이 검증으로 **완료되지 않는 것**

- MSI/DMG를 AudioScoreTool의 **ZIP/TAR 기반 관리형 설치기**가 바로 처리할 수 있는 것은 아닙니다. 앱 소유·버전 고정·SHA 검증이 적용된 **portable archive**, 안전한 업데이트/삭제/복구 테스트가 별도로 필요합니다.
- Windows MSI 콘솔 실행과 macOS DMG 마운트는 CI상의 **추출/실행 검토**일 뿐, 신규 사용자 컴퓨터에 설치된 AudioScoreTool 내부에서 정상 작동한다는 증거가 아닙니다.
- 실제 악보 PDF/PNG → Audiveris → MusicXML/SQLite Song → 최종 export에 대한 end-to-end acceptance는 별도 단계입니다. OMR 품질 벤치마크는 이 단계에도 포함하지 않습니다.
- Audiveris는 AGPL-3.0 계열이므로 제공하는 컴파일된 프로그램, 수정·연결 구성, source offer, 저작권 고지, 제3자 라이브러리/JRE/Tesseract data 및 배포 관계에 대한 **개별 법적 검토**가 필요합니다. 도구가 자동으로 라이선스를 승인할 수 없습니다.
- 특히 OCR 언어팩 공급 경로와 라이선스를 검토·고정하기 전에는 지원되는 텍스트·가사 OMR 기능을 완전한 오프라인 지원으로 선언하지 않습니다.
- Source release의 검증된 바이트·내장 JRE 검사만으로 소프트웨어 서명/공증·독립 upstream 서명·재현 가능한 빌드·클린 머신 검증은 완료되지 않습니다.

따라서 **이 작업의 결과는 항상 `redistribution_status=pending`**이며 `managed-component-catalog.json`을 변경하지 않습니다. 최종 출시 완료는 [#29](https://github.com/JDeun/audio-score-tool/issues/29), 서명 검증은 [#22](https://github.com/JDeun/audio-score-tool/issues/22)에서 분리 관리합니다.
