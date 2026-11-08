# 관리형 런타임 배포 승인 기록

이 파일은 **배포 승인 기록이 아직 없는** 상태로 시작합니다. `managed-component-catalog.json`의 `redistribution_status=approved` 문자열만으로 설치가 활성화되지 않도록, 플랫폼별 원격 바이트 검증 결과와 사람이 검토한 라이선스·소스 제공 조건을 별도로 기록합니다.

**현재 구성:** 모든 관리형 컴포넌트가 미게시 상태입니다. `src/audio_score_tool/managed-release-approvals.json` 파일의 `approvals`가 빈 객체이므로, 앱은 Setup Center의 배포 설치 버튼을 노출하지 않습니다.

## 출고 절차

1. `prepare_managed_artifact_candidate.py`로 해당 플랫폼 로컬 아카이브를 검사하여 승인 대기 후보 JSON 생성
2. **재배포 권한을 확인한 이후**, 이미 업로드된 HTTPS 게시 파일에 대해 `verify_managed_artifact_publication.py --fetch` 실행. 증빙을 별도 검토 위치에 보관하며 검증된 출고 URL·아카이브·도구 해시를 기록
3. 제3자 라이선스, 소스 코드 제공/고지·AGPL·LGPL 의무, 모델 가중치의 상업 사용/재배포 권한, 실제 포함된 FFmpeg 빌드 플래그 등을 담당자가 검토. 검토자의 식별명, 시간, 고지 URL과 SHA-256, 대응 소스 제공 URL을 기록
4. 소유 컴포넌트/플랫폼별 **정확한 카탈로그 객체**를 확정하고, `catalog_fingerprint`로 만든 SHA-256 및 2번에서 생성한 원격 검증 보고서를 함께 기록. 이 두 단계는 개발자가 임의로 `approved` 문자열을 바꾸는 것으로 대체할 수 없음
5. 검토된 카탈로그와 승인 기록을 **같은 PR에서 코드 리뷰 후** 반영. `check_managed_publication.py --require-ready`와 Setup Center API/패키지/clean-machine 테스트 통과 후에만 정식 사용자에게 제공

최소 데이터 형식 (예시를 그대로 출고하지 말 것):

```json
{
  "schema": 1,
  "approvals": {
    "audiveris": {
      "windows-x86_64": {
        "catalog_sha256": "<reviewed exact flattened catalog entry SHA-256>",
        "remote_evidence": {
          "<fields>": "Exact pending JSON from verify_managed_artifact_publication.py"
        },
        "license_review": {
          "decision": "approved",
          "reviewer": "<accountable human reviewer>",
          "reviewed_at_utc": "<reviewed UTC timestamp>",
          "license_reference_url": "https://<reviewed actual license document>",
          "notice_url": "https://<hosted third-party notices>",
          "notice_sha256": "<SHA-256 of actual review notices>",
          "source_offer_url": "https://<corresponding-source-offer>"
        }
      }
    }
  }
}
```

`remote_evidence`는 같은 `component`·`target`·`version`·`upstream_revision`·URL 해시·아카이브 SHA-256·도구별 SHA-256를 포함하며, `remote_artifact_verified=true`, `archive_checked_and_installed_locally=true`, `redistribution_status=pending`, `license_independently_approved=false`로 생성됩니다. 별도 법적 검토 기록이 있어야 앱에서 최종 출고로 볼 수 있습니다.

## 신뢰 경계

- 후보 아카이브 생성 및 원격 검증 도구는 **승인 기록을 자동 작성·승인하지 않습니다**.
- 패키지 환경에서는 번들된 승인 파일만 신뢰합니다. 개발 환경의 `AST_COMPONENT_APPROVALS` 오버라이드는 테스트·검토용이며 packaged 앱에서는 무시합니다.
- 승인 파일을 수동으로 위조할 수 있으므로 이 절차는 **암호학적 서명 또는 변조 불가 제3자 법률 증명서가 아닙니다**. 보호된 GitHub 브랜치(#38), 사람의 정식 승인, 코드 서명·공증(#22) 및 clean-machine 설치 결과가 필요합니다.
- 유효한 승인 기록도 실제 원격 파일 설치 전에 신뢰를 증명하는 것이 아닙니다. 다운로드와 설치시 아카이브·전체 런타임 SHA 검증을 계속 수행하며, 정상 설치/실행 확인은 별도 #29 출고 조건으로 유지합니다.
